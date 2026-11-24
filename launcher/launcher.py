#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""HTPC launcher.

A full-screen home screen driven by a gamepad (or a keyboard):
  * in the middle, one tile per app in apps.json; if the app is already
    running, its tile brings the existing window back (resumes it) instead
    of starting a second copy;
  * clock in the top-left corner, network status in the top-right;
  * in the footer, on the right: edit apps, restart and shut down (the last
    two ask for confirmation). "Edit apps" opens edit mode (see editor.py),
    where shortcuts can be added, edited and removed.

The window uses the app id "htpc-launcher", which is what the GNOME
extension looks for when the guide button asks to show the launcher.

Gamepad:  d-pad or left stick moves, A selects, B goes back;
          on the on-screen keyboard, X deletes and Y types a space.
Keyboard: arrows move, Enter selects, Esc goes back.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from gi.repository import GLib

# Must run before GTK is loaded: on Wayland the window's app id comes from this.
GLib.set_prgname("htpc-launcher")
GLib.set_application_name("HTPC Launcher")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, Gio, Gtk, Pango  # noqa: E402

try:
    import evdev
    from evdev import ecodes
except ImportError:  # without evdev the launcher still works with a keyboard
    evdev = None

HERE = Path(__file__).resolve().parent
# Installed side by side; in the repo, htpc_config.py lives in common/.
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / "common"))
import htpc_config  # noqa: E402
from editor import EditorMixin  # noqa: E402
from i18n import Translator  # noqa: E402
import themes  # noqa: E402

CSS = HERE / "launcher.css"
ICONS = HERE / "icons"
# Icons chosen by the user; offered as options in the app editor.
APP_ICONS = Path.home() / ".local/share/htpc-launcher/app-icons"
LAUNCHER_ID = "htpc-launcher"
OPENING_GRACE = 20   # seconds an app counts as "opening" and is not started again
RESUME_DELAY = 1500  # ms to wait after on_resume before raising the app's window
COLUMNS = 5          # tiles per row; more apps wrap onto more rows

# Where Flatpak publishes the .desktop files and icons of installed apps. They are
# usually on the session's XDG_DATA_DIRS already; looking here too covers when not.
FLATPAK_EXPORTS = [Path.home() / ".local/share/flatpak/exports/share",
                   Path("/var/lib/flatpak/exports/share")]


def log(*args):
    print("[launcher]", *args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# GNOME extension (D-Bus org.htpc.Launcher)

class Bridge:
    def __init__(self):
        self.proxy = None
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.DO_NOT_AUTO_START | Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
                None, "org.htpc.Launcher", "/org/htpc/Launcher", "org.htpc.Launcher", None)
        except GLib.Error as e:
            log("no D-Bus:", e.message)

    def call(self, method, signature=None, *args):
        if self.proxy is None:
            return None
        params = GLib.Variant(signature, args) if signature else None
        try:
            r = self.proxy.call_sync(method, params, Gio.DBusCallFlags.NONE, 2000, None)
            return r.unpack()[0] if r is not None else None
        except GLib.Error as e:
            log(f"extension did not answer {method}:", e.message)
            return None

    def activate(self, app_id, titles=None):
        if titles:
            r = self.call("ActivatePreferring", "(sas)", app_id, list(titles))
            if r is not None:
                return bool(r)
            # older extension without that method: bring any window of the app
        return bool(self.call("Activate", "(s)", app_id))

    def is_running(self, app_id):
        return bool(self.call("IsRunning", "(s)", app_id))

    def on_focus_changed(self, callback):
        if self.proxy is not None:
            self.proxy.connect("g-signal", lambda _p, _s, signal, _a:
                               signal == "FocusChanged" and callback())


# ---------------------------------------------------------------------------
# Gamepad (evdev). The launcher only acts on buttons while it is in front.

class Gamepad:
    DEAD_ZONE = 0.55      # how far the stick must go to count as a press
    REPEAT_AFTER = 0.40   # holding a direction repeats after this...
    REPEAT_EVERY = 0.14   # ...at this pace

    def __init__(self, active, move, press, back, other_button=None):
        self.active, self.move, self.press, self.back = active, move, press, back
        self.other_button = other_button or (lambda _name: None)  # "x" or "y"
        self.devs, self.ignored, self.watches = {}, set(), {}
        self.axes = {}          # (path, axis) -> current direction (-1, 0, 1)
        self.direction = None   # (dx, dy) being held
        self.repeat = 0
        if evdev is None:
            log("python3-evdev not installed: keyboard only")
            return
        self.rescan()
        GLib.timeout_add_seconds(2, self.rescan)

    def rescan(self):
        paths = set(evdev.list_devices())
        self.ignored &= paths
        for path in paths - self.devs.keys() - self.ignored:
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                self.ignored.add(path)
                continue
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            if ecodes.BTN_SOUTH in keys and ecodes.BTN_START in keys:
                self.devs[path] = dev
                self.watches[path] = GLib.io_add_watch(
                    dev.fd, GLib.PRIORITY_DEFAULT,
                    GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                    self._read, path)
                log("gamepad:", dev.name)
            else:
                dev.close()
                self.ignored.add(path)
        return True

    def _remove(self, path):
        dev = self.devs.pop(path, None)
        self.watches.pop(path, None)
        for key in [k for k in self.axes if k[0] == path]:
            del self.axes[key]
        if dev:
            try:
                dev.close()
            except OSError:
                pass

    def _read(self, _fd, _cond, path):
        dev = self.devs.get(path)
        if dev is None:
            return False
        try:
            events = list(dev.read())
        except BlockingIOError:
            return True
        except OSError:
            self._remove(path)
            return False
        for ev in events:
            self._event(path, dev, ev)
        return True

    def _event(self, path, dev, ev):
        if ev.type == ecodes.EV_KEY and ev.value in (0, 1):
            dpad = {ecodes.BTN_DPAD_LEFT: (-1, 0), ecodes.BTN_DPAD_RIGHT: (1, 0),
                    ecodes.BTN_DPAD_UP: (0, -1), ecodes.BTN_DPAD_DOWN: (0, 1)}
            if ev.code in dpad:
                self._hold(dpad[ev.code] if ev.value else None)
            elif ev.value == 1 and self.active():
                if ev.code == ecodes.BTN_SOUTH:
                    self.press()
                elif ev.code == ecodes.BTN_EAST:
                    self.back()
                elif ev.code == ecodes.BTN_WEST:
                    self.other_button("x")
                elif ev.code == ecodes.BTN_NORTH:
                    self.other_button("y")
        elif ev.type == ecodes.EV_ABS:
            if ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_HAT0Y):
                value = max(-1, min(1, ev.value))
            elif ev.code in (ecodes.ABS_X, ecodes.ABS_Y):
                info = dev.absinfo(ev.code)
                middle = (info.max + info.min) / 2
                half = (info.max - info.min) / 2 or 1
                frac = (ev.value - middle) / half
                value = 1 if frac > self.DEAD_ZONE else -1 if frac < -self.DEAD_ZONE else 0
            else:
                return
            key = (path, ev.code)
            if self.axes.get(key, 0) == value:
                return
            self.axes[key] = value
            horizontal = ev.code in (ecodes.ABS_HAT0X, ecodes.ABS_X)
            if value:
                self._hold((value, 0) if horizontal else (0, value))
            elif self.direction and ((horizontal and self.direction[0]) or (not horizontal and self.direction[1])):
                self._hold(None)

    def _hold(self, direction):
        if self.repeat:
            GLib.source_remove(self.repeat)
            self.repeat = 0
        self.direction = direction
        if direction is None or not self.active():
            return
        self.move(*direction)
        self.repeat = GLib.timeout_add(int(self.REPEAT_AFTER * 1000), self._start_repeat)

    def _start_repeat(self):
        self.repeat = GLib.timeout_add(int(self.REPEAT_EVERY * 1000), self._repeat)
        return False

    def _repeat(self):
        if self.direction is None or not self.active():
            self.repeat = 0
            return False
        self.move(*self.direction)
        return True


# ---------------------------------------------------------------------------
# Icons

def desktop_info(name):
    try:
        info = Gio.DesktopAppInfo.new(name)
    except TypeError:
        info = None
    if info:
        return info
    for base in FLATPAK_EXPORTS:
        path = base / "applications" / name
        if path.exists():
            return Gio.DesktopAppInfo.new_from_filename(str(path))
    return None


def app_icon(app):
    """The icon the app installed itself (through its .desktop file), or a generic one.

    "icon" in apps.json overrides it: a theme icon name or an image file path.
    """
    if app.get("icon"):
        icon = os.path.expanduser(app["icon"])
        if not os.path.isabs(icon):
            return Gio.ThemedIcon.new(icon)
        if os.path.exists(icon):
            return Gio.FileIcon.new(Gio.File.new_for_path(icon))
        log("icon not found:", icon, "- using the app's own")
    if not app.get("id") and not app.get("desktop"):
        return Gio.ThemedIcon.new("application-x-executable")
    for desktop in (app.get("desktop"), f"{app.get('id')}.desktop"):
        if not desktop:
            continue
        info = desktop_info(desktop)
        if info and info.get_icon():
            return info.get_icon()
    # Flatpak also publishes the icon under the app id itself.
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    if app.get("id") and theme.has_icon(app["id"]):
        return Gio.ThemedIcon.new(app["id"])
    log("no icon for", app.get("name"), "- is the app installed?")
    return Gio.ThemedIcon.new("application-x-executable")


# ---------------------------------------------------------------------------
# Tiles

class Tile(Gtk.Button):
    def __init__(self, app, on_activate):
        super().__init__()
        self.app = app
        self.add_css_class("tile")
        self.set_focus_on_click(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_gicon(app_icon(app))
        image.set_pixel_size(128)
        image.add_css_class("tile-icon")
        name = Gtk.Label(label=app.get("name", "?"), ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        name.add_css_class("tile-name")
        self.status = Gtk.Label(label="")
        self.status.add_css_class("tile-status")
        for w in (image, name, self.status):
            box.append(w)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_activate(self))

    def show_status(self, text, running=False):
        self.status.set_label(text)
        if running:
            self.add_css_class("running")
        else:
            self.remove_css_class("running")


class AddTile(Gtk.Button):
    """The "+ Add" tile shown at the end of the list in edit mode."""

    def __init__(self, label, on_activate):
        super().__init__()
        self.add_css_class("tile")
        self.add_css_class("tile-add")
        self.set_focus_on_click(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER)
        plus = Gtk.Label(label="+")
        plus.add_css_class("tile-plus")
        name = Gtk.Label(label=label)
        name.add_css_class("tile-name")
        box.append(plus)
        box.append(name)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_activate())


# ---------------------------------------------------------------------------
# The launcher window

class Launcher(EditorMixin):
    # What the edit mode (editor.py) uses from here, without importing this file.
    app_icon = staticmethod(app_icon)
    desktop_info = staticmethod(desktop_info)
    app_icons_dir = APP_ICONS
    flatpak_exports = FLATPAK_EXPORTS
    launcher_id = LAUNCHER_ID

    def __init__(self, gtk_app):
        self.gtk_app = gtk_app
        self.cfg, migrated = htpc_config.load()
        if migrated:
            htpc_config.save(self.cfg)
            log("apps.json converted to the current format")
        self.t = Translator(self.cfg.get("language"))
        self.bridge = Bridge()

        # Background color: its own CSS provider, above launcher.css, so it can change live.
        self.theme_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.apply_theme(self.cfg.get("background", themes.DEFAULT_THEME))

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for base in FLATPAK_EXPORTS:
            if (base / "icons").is_dir():
                theme.add_search_path(str(base / "icons"))
        self.opening = {}         # app id -> when it was started
        self.overlays = []        # stack of things shown on top (confirmation, editor...)
        self.editing = False
        self.tiles, self.add_tile, self.tile_rows = [], None, []

        self.win = Gtk.Window(application=gtk_app, title="HTPC")
        self.win.add_css_class("htpc")
        self.win.set_default_size(1920, 1080)

        self.overlay = Gtk.Overlay()
        self.win.set_child(self.overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        self.overlay.set_child(root)

        root.append(self._top_bar())
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True)
        root.append(self.grid)
        root.append(self._footer())
        self.build_grid()

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.win.add_controller(keys)

        self.win.connect("notify::is-active", lambda *_: self.win.is_active() and self.refresh_status())
        self.bridge.on_focus_changed(self.refresh_status)

        self.gamepad = Gamepad(self.win.is_active, self.move, self.press, self.back, self.other_button)

        self._update_clock()
        GLib.timeout_add_seconds(1, self._update_clock)
        self.network = Gio.NetworkMonitor.get_default()
        self.network.connect("notify::connectivity", lambda *_: self._update_network())
        self.network.connect("network-changed", lambda *_: self._update_network())
        self._update_network()
        GLib.timeout_add_seconds(3, self._every_3s)

        self.win.set_cursor(Gdk.Cursor.new_from_name("none", None))
        self.win.fullscreen()
        self.win.present()
        if self.tiles:
            self.tiles[0].grab_focus()

    @property
    def rows(self):
        footer = [self.btn_background] if self.editing else []
        return self.tile_rows + [footer + [self.btn_settings, self.btn_restart, self.btn_power]]

    def apply_theme(self, theme_id):
        """Switch the background color right away (does not save it)."""
        if theme_id not in themes.THEMES:
            theme_id = themes.DEFAULT_THEME
        self.theme = theme_id
        css = themes.css(theme_id)
        if hasattr(self.theme_provider, "load_from_string"):  # GTK 4.12+
            self.theme_provider.load_from_string(css)
        else:
            self.theme_provider.load_from_data(css, -1)

    # --- app grid ------------------------------------------------------------

    def build_grid(self, focus=None):
        """(Re)build the app tiles, in rows of up to COLUMNS.

        focus: index of the app to focus afterwards; -1 means the "+ Add" tile.
        """
        child = self.grid.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.grid.remove(child)
            child = following

        self.tiles = [Tile(a, self.on_tile) for a in self.cfg.get("apps", [])]
        items = list(self.tiles)
        self.add_tile = None
        if self.editing:
            self.add_tile = AddTile(self.t("add"), self.new_app)
            items.append(self.add_tile)
            for tile in self.tiles:
                tile.add_css_class("editing")

        self.tile_rows = [items[i:i + COLUMNS] for i in range(0, len(items), COLUMNS)]
        for row in self.tile_rows:
            box = Gtk.Box(spacing=48, halign=Gtk.Align.CENTER)
            for w in row:
                box.append(w)
            self.grid.append(box)

        self.refresh_status()
        if focus is not None:
            target = self.add_tile if focus == -1 or not self.tiles else self.tiles[min(focus, len(self.tiles) - 1)]
            if target is not None:
                target.grab_focus()

    def on_tile(self, tile):
        if self.editing:
            self.edit_app(self.tiles.index(tile))
        else:
            self.open_app(tile)

    def save_config(self):
        htpc_config.save(self.cfg)
        log("apps.json saved")

    # --- top bar ---------------------------------------------------------------

    def _top_bar(self):
        """Console style: clock in the left corner, network status alone on the right."""
        bar = Gtk.Box()
        bar.add_css_class("top-bar")

        clock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START, hexpand=True)
        self.time_label = Gtk.Label(label="", xalign=0)
        self.time_label.add_css_class("clock")
        self.date_label = Gtk.Label(label="", xalign=0)
        self.date_label.add_css_class("date")
        clock.append(self.time_label)
        clock.append(self.date_label)

        # Connected: just the icon. Text only when something is wrong.
        net = Gtk.Box(spacing=10, valign=Gtk.Align.START)
        net.add_css_class("network")
        self.net_text = Gtk.Label(label="")
        self.net_icon = Gtk.Image()
        self.net_icon.set_pixel_size(30)
        net.append(self.net_text)
        net.append(self.net_icon)

        bar.append(clock)
        bar.append(net)
        return bar

    # --- footer ----------------------------------------------------------------

    def _footer(self):
        bar = Gtk.Box(spacing=14)
        bar.add_css_class("footer")

        self.hint = Gtk.Label(label=self.t("hint_normal"), hexpand=True, xalign=0)
        self.hint.add_css_class("hint")
        bar.append(self.hint)

        # Only shown in edit mode, next to "Done".
        self.btn_background = self._footer_button("background.svg", self.t("background"), self.choose_background)
        self.btn_background.set_visible(False)
        self.btn_settings = self._footer_button("settings.svg", self.t("edit_apps"), self.toggle_edit_mode)
        self.btn_restart = self._footer_button("restart.svg", self.t("restart"),
                                               lambda: self.confirm_power("restart"))
        self.btn_power = self._footer_button("power.svg", self.t("power_off"),
                                             lambda: self.confirm_power("power_off"))
        for b in (self.btn_background, self.btn_settings, self.btn_restart, self.btn_power):
            bar.append(b)
        return bar

    def _footer_button(self, icon, text, action):
        b = Gtk.Button()
        b.add_css_class("footer-button")
        b.set_focus_on_click(False)
        box = Gtk.Box(spacing=8)
        image = Gtk.Image.new_from_file(str(ICONS / icon))
        image.set_pixel_size(20)
        b.label = Gtk.Label(label=text)
        b.label.add_css_class("footer-button-label")
        box.append(image)
        box.append(b.label)
        b.set_child(box)
        b.connect("clicked", lambda _b: action())
        return b

    def _update_clock(self):
        now = GLib.DateTime.new_now_local()
        self.time_label.set_label(now.format("%H:%M"))
        self.date_label.set_label(self.t.date(now.get_day_of_week(), now.get_day_of_month(), now.get_month()))
        return True

    def _update_network(self):
        c = self.network.get_connectivity()
        if not self.network.get_network_available() or c == Gio.NetworkConnectivity.LOCAL:
            text, icon, state = self.t("no_internet"), "wifi-off.svg", "off"
        elif c == Gio.NetworkConnectivity.FULL:
            text, icon, state = "", "wifi.svg", "on"
        else:  # LIMITED or PORTAL
            text, icon, state = self.t("limited_internet"), "wifi-limited.svg", "limited"
        self.net_icon.set_from_file(str(ICONS / icon))
        self.net_icon.set_pixel_size(30)
        self.net_text.set_label(text)
        self.net_text.set_visible(bool(text))
        for s in ("on", "off", "limited"):
            self.net_text.remove_css_class(s)
        self.net_text.add_css_class(state)
        self.network_state = state

    def _every_3s(self):
        if self.win.is_active() and not self.overlays:
            self.refresh_status()
        return True

    # --- apps --------------------------------------------------------------------

    def refresh_status(self):
        now = time.monotonic()
        for tile in self.tiles:
            if self.editing:
                tile.show_status(self.t("status_edit"))
                continue
            app_id = tile.app["id"]
            if self.bridge.is_running(app_id):
                self.opening.pop(app_id, None)
                tile.show_status(self.t("status_open"), running=True)
            elif now - self.opening.get(app_id, -1e9) < OPENING_GRACE:
                tile.show_status(self.t("status_opening"), running=True)
            else:
                self.opening.pop(app_id, None)
                tile.show_status("")
        return False

    def _spawn(self, command):
        try:
            subprocess.Popen(command, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as e:
            log("could not start", command, e)
            return False

    def open_app(self, tile):
        app = tile.app
        app_id = app["id"]
        windows = app.get("preferred_windows")
        if self.bridge.activate(app_id, windows):
            log("resuming", app["name"])
            on_resume = app.get("on_resume")
            if on_resume and self._spawn(on_resume):
                # e.g. Steam switching to Big Picture opens a new window; bring it up.
                GLib.timeout_add(RESUME_DELAY, lambda: self.bridge.activate(app_id, windows) and False)
            return
        if time.monotonic() - self.opening.get(app_id, -1e9) < OPENING_GRACE:
            log(app["name"], "is still opening")
            return
        command = app.get("launch")
        if not command:
            log("no launch command for", app["name"])
            return
        log("starting", app["name"], command)
        if self._spawn(command):
            self.opening[app_id] = time.monotonic()
            tile.show_status(self.t("status_opening"), running=True)

    # --- things shown on top (confirmations, editor, lists) ------------------------

    def push_overlay(self, content, rows, focus=None, **hooks):
        """Show `content` on top of the screen, dimming the background.

        rows: navigable buttons, in rows (like the app grid).
        hooks: optional callbacks for this overlay — type(text), delete(), space(), enter().
        """
        backdrop = Gtk.Box(halign=Gtk.Align.FILL, valign=Gtk.Align.FILL)
        backdrop.add_css_class("dialog-backdrop")
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)
        content.set_hexpand(True)
        backdrop.append(content)
        self.overlay.add_overlay(backdrop)
        self.overlays.append(dict(backdrop=backdrop, rows=rows, focus_before=self.win.get_focus(), **hooks))
        target = focus or (rows[0][0] if rows and rows[0] else None)
        if target is not None:
            target.grab_focus()

    def pop_overlay(self):
        if not self.overlays:
            return
        top = self.overlays.pop()
        self.overlay.remove_overlay(top["backdrop"])
        previous = top["focus_before"]
        if previous is not None and previous.get_root() is not None:
            previous.grab_focus()
        elif self.overlays:
            self.overlays[-1]["rows"][0][0].grab_focus()
        elif self.tiles:
            self.tiles[0].grab_focus()

    def dialog_box(self, title, text=None):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        box.add_css_class("dialog")
        label = Gtk.Label(label=title)
        label.add_css_class("dialog-title")
        box.append(label)
        if text:
            note = Gtk.Label(label=text, wrap=True, max_width_chars=60, justify=Gtk.Justification.CENTER)
            note.add_css_class("dialog-text")
            box.append(note)
        return box

    def dialog_button(self, text, action, danger=False):
        b = Gtk.Button(label=text)
        b.add_css_class("dialog-button")
        if danger:
            b.add_css_class("danger")
        b.set_focus_on_click(False)
        b.connect("clicked", lambda _b: action())
        return b

    def confirm(self, title, text, yes_label, on_yes, danger=True):
        """Yes/no question. Focus starts on Cancel."""
        box = self.dialog_box(title, text)
        buttons = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        cancel = self.dialog_button(self.t("cancel"), self.pop_overlay)
        yes = self.dialog_button(yes_label, lambda: (self.pop_overlay(), on_yes()), danger)
        buttons.append(cancel)
        buttons.append(yes)
        box.append(buttons)
        self.push_overlay(box, [[cancel, yes]], focus=cancel)

    # --- restart / shut down ----------------------------------------------------------

    def confirm_power(self, action):
        title = self.t("confirm_restart") if action == "restart" else self.t("confirm_power_off")
        label = self.t("restart") if action == "restart" else self.t("power_off")
        self.confirm(title, self.t("power_warning"), label, lambda: self._run_power(action))

    def _run_power(self, action):
        command = ["systemctl", "reboot" if action == "restart" else "poweroff"]
        log("running", command)
        subprocess.Popen(command, start_new_session=True)

    # --- navigation ---------------------------------------------------------------------

    def _current_rows(self):
        return self.overlays[-1]["rows"] if self.overlays else self.rows

    def _center_x(self, w):
        ok, r = w.compute_bounds(self.win)
        return r.get_x() + r.get_width() / 2 if ok else 0

    def move(self, dx, dy):
        rows = [r for r in self._current_rows() if r]
        if not rows:
            return
        focused = self.win.get_focus()
        pos = next(((i, j) for i, row in enumerate(rows)
                    for j, w in enumerate(row) if w is focused), None)
        if pos is None:
            target = rows[0][0]
        elif dx:
            i, j = pos
            target = rows[i][max(0, min(len(rows[i]) - 1, j + dx))]
        else:
            i = max(0, min(len(rows) - 1, pos[0] + dy))
            if i == pos[0]:
                return
            x = self._center_x(focused)
            target = min(rows[i], key=lambda w: abs(self._center_x(w) - x))
        target.grab_focus()

    def press(self):
        focused = self.win.get_focus()
        if isinstance(focused, Gtk.Button):
            focused.emit("clicked")

    def back(self):
        if self.overlays:
            cancel = self.overlays[-1].get("cancel")
            if cancel:
                cancel()
            self.pop_overlay()
        elif self.editing:
            self.toggle_edit_mode()

    def other_button(self, name):
        hook = {"x": "delete", "y": "space"}[name]
        if self.overlays and self.overlays[-1].get(hook):
            self.overlays[-1][hook]()

    def _on_key(self, _ctl, keyval, _code, _mods):
        top = self.overlays[-1] if self.overlays else {}
        if top.get("type"):  # on-screen keyboard open: a real keyboard types too
            if keyval == Gdk.KEY_BackSpace:
                top["delete"]()
                return True
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                top["enter"]()
                return True
            char = chr(Gdk.keyval_to_unicode(keyval) or 0)
            if char and char.isprintable():
                top["type"](char)
                return True
        directions = {Gdk.KEY_Left: (-1, 0), Gdk.KEY_Right: (1, 0),
                      Gdk.KEY_Up: (0, -1), Gdk.KEY_Down: (0, 1)}
        if keyval in directions:
            self.move(*directions[keyval])
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.press()
        elif keyval == Gdk.KEY_Escape:
            self.back()
        else:
            return False
        return True


def main():
    if not htpc_config.CONFIG_PATH.exists():
        raise SystemExit(f"Missing configuration file: {htpc_config.CONFIG_PATH}")

    # Is a launcher already open? Then just bring it to the front.
    if Bridge().activate(LAUNCHER_ID):
        log("already running")
        return

    app = Gtk.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
    state = {}

    def activate(a):
        if "launcher" in state:
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        state["launcher"] = Launcher(a)

    app.connect("activate", activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
