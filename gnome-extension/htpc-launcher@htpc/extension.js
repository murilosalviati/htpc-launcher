// HTPC Launcher Bridge
//
// No Wayland um programa comum não pode trazer janelas para a frente nem
// saber qual janela está em foco. A extensão roda dentro do próprio GNOME
// Shell, então pode — e oferece isso ao launcher e ao serviço do controle
// pelo D-Bus de sessão:
//
//   nome:    org.htpc.Launcher
//   objeto:  /org/htpc/Launcher
//
// Um "appId" pode ser qualquer um destes (sem diferenciar maiúsculas):
//   - id do .desktop sem a extensão   (org.jellyfin.JellyfinDesktop)
//   - id do Flatpak                   (rocks.shy.VacuumTube)
//   - WM_CLASS da janela               (steam)

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// appId da janela do próprio launcher (ele vai definir esse WM_CLASS / app id).
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
    <method name="FocusedApp">
      <arg type="s" direction="out" name="appId"/>
    </method>
    <method name="Close">
      <arg type="s" direction="in" name="appId"/>
      <arg type="u" direction="out" name="closedWindows"/>
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
// Identificação de janelas

function normalWindows() {
    return global.get_window_actors()
        .map(actor => actor.get_meta_window())
        .filter(win => win && win.get_window_type() === Meta.WindowType.NORMAL);
}

// Todos os nomes pelos quais a janela pode ser chamada, em minúsculas.
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

// Nome "principal" da janela, o que é devolvido pelos métodos.
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
        // a usada por último primeiro
        .sort((a, b) => b.get_user_time() - a.get_user_time());
}

// ---------------------------------------------------------------------------
// Objeto exportado no D-Bus

class LauncherBridge {
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

    // Traz para a frente a janela já aberta do app (retoma a sessão).
    // Devolve false se o app não tem janela — aí o launcher deve abri-lo.
    Activate(appId) {
        const [win] = windowsOf(appId);
        if (!win)
            return false;
        if (win.minimized)
            win.unminimize();
        Main.activateWindow(win, global.get_current_time());
        return true;
    }

    FocusedApp() {
        const win = global.display.focus_window;
        return win ? primaryId(win) : '';
    }

    // Pede para as janelas do app fecharem (como clicar no X).
    // Matar o processo, se ele não fechar, fica a cargo de quem chamou.
    Close(appId) {
        const wins = windowsOf(appId);
        const now = global.get_current_time();
        for (const win of wins)
            win.delete(now);
        return wins.length;
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

        this._focusId = global.display.connect('notify::focus-window', () => {
            const appId = this._impl.FocusedApp();
            this._dbus.emit_signal('FocusChanged', new GLib.Variant('(s)', [appId]));
        });
    }

    disable() {
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
