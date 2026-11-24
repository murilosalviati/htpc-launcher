// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Murilo Salviati
// HTPC Launcher Bridge
//
// On Wayland a regular program cannot raise windows or find out which window
// has focus. This extension runs inside GNOME Shell itself, so it can, and it
// offers that to the launcher and the controller service on the session bus:
//
//   name:    org.htpc.Launcher
//   object:  /org/htpc/Launcher
//
// An "appId" can be any of these (case-insensitive):
//   - the .desktop id without the extension   (org.jellyfin.JellyfinDesktop)
//   - the Flatpak id                          (rocks.shy.VacuumTube)
//   - the window's WM_CLASS                   (steam)

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// appId of the launcher's own window (it sets this WM_CLASS / app id).
const LAUNCHER_ID = 'htpc-launcher';

const BUS_NAME = 'org.htpc.Launcher';
const OBJECT_PATH = '/org/htpc/Launcher';

const IFACE_XML = `
<node>
  <interface name="org.htpc.Launcher">
    <method name="ListWindows">
      <arg type="s" direction="out" name="json"/>
    </method>
    <method name="IsRunning">
      <arg type="s" direction="in" name="appId"/>
      <arg type="b" direction="out" name="running"/>
    </method>
    <method name="Activate">
      <arg type="s" direction="in" name="appId"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="ActivatePreferring">
      <arg type="s" direction="in" name="appId"/>
      <arg type="as" direction="in" name="titles"/>
      <arg type="b" direction="out" name="ok"/>
    </method>
    <method name="FocusedApp">
      <arg type="s" direction="out" name="appId"/>
    </method>
    <method name="Close">
      <arg type="s" direction="in" name="appId"/>
      <arg type="u" direction="out" name="closedWindows"/>
    </method>
    <method name="FullscreenOnOpen">
      <arg type="s" direction="in" name="appId"/>
      <arg type="u" direction="in" name="seconds"/>
      <arg type="u" direction="out" name="windowsNow"/>
    </method>
    <method name="ShowLauncher">
      <arg type="b" direction="out" name="ok"/>
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="appId"/>
    </signal>
  </interface>
</node>`;

// ---------------------------------------------------------------------------
// Identifying windows

function normalWindows() {
    return global.get_window_actors()
        .map(actor => actor.get_meta_window())
        .filter(win => win && win.get_window_type() === Meta.WindowType.NORMAL);
}

// Every name the window can be called by, in lowercase.
function windowIds(win) {
    const ids = new Set();
    const app = Shell.WindowTracker.get_default().get_window_app(win);
    const appId = app?.get_id();
    if (appId)
        ids.add(appId.replace(/\.desktop$/, ''));

    const extra = [
        win.get_sandboxed_app_id?.(),
        win.get_gtk_application_id?.(),
        win.get_wm_class(),
        win.get_wm_class_instance(),
    ];
    for (const v of extra) {
        if (v)
            ids.add(v);
    }
    return [...ids].map(s => s.toLowerCase());
}

// The window's "main" name, the one the methods return.
function primaryId(win) {
    const sandboxed = win.get_sandboxed_app_id?.();
    if (sandboxed)
        return sandboxed;
    const app = Shell.WindowTracker.get_default().get_window_app(win);
    const appId = app?.get_id();
    if (appId && !appId.startsWith('window:'))
        return appId.replace(/\.desktop$/, '');
    return win.get_wm_class() ?? '';
}

function windowsOf(appId) {
    const wanted = (appId ?? '').trim().toLowerCase();
    if (!wanted)
        return [];
    return normalWindows()
        .filter(win => windowIds(win).includes(wanted))
        // most recently used first
        .sort((a, b) => b.get_user_time() - a.get_user_time());
}

// ---------------------------------------------------------------------------
// Object exported on D-Bus

// A window worth making full screen: a normal top-level window, not a dialog.
function fullscreenable(win) {
    return win && win.get_window_type() === Meta.WindowType.NORMAL &&
        !win.get_transient_for() && !win.is_fullscreen();
}

class LauncherBridge {
    constructor() {
        this._fullscreenWanted = new Map();  // appId (lowercase) -> until when (µs, monotonic)
    }

    ListWindows() {
        const focused = global.display.focus_window;
        const list = normalWindows().map(win => ({
            appId: primaryId(win),
            ids: windowIds(win),
            title: win.get_title() ?? '',
            pid: win.get_pid(),
            minimized: win.minimized,
            focused: win === focused,
        }));
        return JSON.stringify(list);
    }

    IsRunning(appId) {
        return windowsOf(appId).length > 0;
    }

    // Raises the app's existing window (resumes it).
    // Returns false if the app has no window; then the launcher should start it.
    Activate(appId) {
        return this.ActivatePreferring(appId, []);
    }

    // Like Activate, for apps with several windows (Steam opens "Steam",
    // "Friends List", "Special Offers"...): raises the first window whose title
    // is in `titles`, in the given order; if none match, the most recent one.
    ActivatePreferring(appId, titles) {
        const wins = windowsOf(appId);
        if (wins.length === 0)
            return false;
        let win = wins[0];
        for (const title of titles ?? []) {
            const match = wins.find(w => w.get_title() === title);
            if (match) {
                win = match;
                break;
            }
        }
        if (win.minimized)
            win.unminimize();
        Main.activateWindow(win, global.get_current_time());
        return true;
    }

    FocusedApp() {
        const win = global.display.focus_window;
        return win ? primaryId(win) : '';
    }

    // Asks the app's windows to close (like clicking X).
    // Killing the process if it does not close is up to the caller.
    Close(appId) {
        const wins = windowsOf(appId);
        const now = global.get_current_time();
        for (const win of wins)
            win.delete(now);
        return wins.length;
    }

    // Puts the app's windows in full screen: the ones it has now and any it
    // opens in the next `seconds` (an app being started has no window yet).
    FullscreenOnOpen(appId, seconds) {
        const wanted = (appId ?? '').trim().toLowerCase();
        if (!wanted)
            return 0;
        this._fullscreenWanted.set(wanted, GLib.get_monotonic_time() + seconds * 1e6);
        const wins = windowsOf(wanted).filter(fullscreenable);
        for (const win of wins)
            win.make_fullscreen();
        return wins.length;
    }

    // Called for every new window.
    windowCreated(win) {
        const now = GLib.get_monotonic_time();
        for (const [id, until] of this._fullscreenWanted) {
            if (until < now)
                this._fullscreenWanted.delete(id);
        }
        if (this._fullscreenWanted.size === 0)
            return;
        // Wait a moment: right after creation the window may not have its app id
        // or type yet, and some apps resize themselves when they first appear.
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => {
            if (!win.get_compositor_private())
                return GLib.SOURCE_REMOVE;  // already gone
            const ids = windowIds(win);
            if (fullscreenable(win) && ids.some(id => this._fullscreenWanted.has(id)))
                win.make_fullscreen();
            return GLib.SOURCE_REMOVE;
        });
    }

    ShowLauncher() {
        return this.Activate(LAUNCHER_ID);
    }
}

// ---------------------------------------------------------------------------

export default class HtpcLauncherExtension extends Extension {
    enable() {
        this._impl = new LauncherBridge();
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this._impl);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);

        this._nameId = Gio.bus_own_name_on_connection(
            Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null);

        this._createdId = global.display.connect('window-created',
            (_display, win) => this._impl.windowCreated(win));

        this._focusId = global.display.connect('notify::focus-window', () => {
            const appId = this._impl.FocusedApp();
            this._dbus.emit_signal('FocusChanged', new GLib.Variant('(s)', [appId]));
        });
    }

    disable() {
        if (this._createdId) {
            global.display.disconnect(this._createdId);
            this._createdId = 0;
        }
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._impl = null;
    }
}
