#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""HTPC launcher.

A full-screen home screen driven by a gamepad (or a keyboard):
  * in the middle, one tile per app in apps.json; if the app is already
    running, its tile brings the existing window back (resumes it) instead
    of starting a second copy;
  * above the apps, what was added to Jellyfin lately; below them (scrolled
    into view by going down), lights and switches from Home Assistant
    (see home.py);
  * top bar: the weather on the left (if a location is set); on the right
    gamepad and network status, the clock, and settings, restart and shut
    down (the last two ask for confirmation). Settings (see settings.py) has the apps
    (edit mode, see editor.py), the background, the weather location, the
    temperature unit and the language.

Everything that depends on the operating system (finding and raising
windows, reading gamepads, the installed-apps list, restart and shut down)
goes through the backend from htpc.backends; this file is only the GTK UI.

The window uses the app id "htpc-launcher", which is what the window control
looks for when the guide button asks to show the launcher.

Gamepad:  d-pad or left stick moves, A selects, B goes back;
          on the on-screen keyboard, X deletes and Y types a space.
Keyboard: arrows move, Enter selects, Esc goes back.
"""

import os
import sys
import time
from pathlib import Path

from gi.repository import GLib

# Must run before GTK is loaded: on Wayland the window's app id comes from this.
GLib.set_prgname("htpc-launcher")

# Started at login, GTK asks xdg-desktop-portal for settings before the portal
# is up and waits for it to time out: the window appeared ~50 s late. The
# launcher needs nothing from the portal. Removed again once GTK is up, so the
# apps it starts use portals normally.
os.environ["GDK_DEBUG"] = ",".join(filter(None, [os.environ.get("GDK_DEBUG"), "no-portals"]))
GLib.set_application_name("HTPC Launcher")

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, Gio, Gsk, Gtk, Pango  # noqa: E402

try:   # GLib 2.80+ moved the Unix fd watch to GLibUnix (the GLib one warns there)
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix  # noqa: E402
    unix_fd_add = GLibUnix.fd_add_full
except (ValueError, ImportError):
    unix_fd_add = GLib.unix_fd_add_full

HERE = Path(__file__).resolve().parent
# Installed: the htpc package sits next to this file. In the repo: one folder up.
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
from htpc import config, home_assistant, paths, shortcuts, themes, weather  # noqa: E402
from htpc.backends import get_backend  # noqa: E402
from htpc.backends.base import STICK_DEAD_ZONE, pick_mode  # noqa: E402
from htpc.i18n import Translator  # noqa: E402
from background import in_background  # noqa: E402
from editor import EditorMixin  # noqa: E402
from home import HOUSE_EVERY, HomeMixin  # noqa: E402
from screensaver import ScreensaverMixin  # noqa: E402
from settings import SettingsMixin  # noqa: E402

CSS = HERE / "launcher.css"
ICONS = HERE / "icons"
LAUNCHER_ID = "htpc-launcher"
OPENING_GRACE = 20   # seconds an app counts as "opening" and is not started again
FULLSCREEN_FOR = 60  # seconds after starting an app during which its new windows go full screen
DISPLAY_APP_GRACE = 15  # seconds after switching to an app's resolution before the launcher may undo it
RESUME_DELAY = 1500  # ms to wait after on_resume before raising the app's window
COLUMNS = 5          # tiles per row; more apps wrap onto more rows
PRESS_MS = 260       # length of the "button pushed" animation of a tile
PRESS_DELAY = 140    # ms between pushing a tile and acting, so the push is seen
                     # before an app window covers the screen (0: act right away)
# Sizes of what sits on the edges (top bar and footer), for a 1920×1080 screen.
# They are multiplied by how much bigger or smaller the screen is (see
# apply_edge_scale), so they keep the same share of the screen on any TV.
EDGE = {
    "clock": 56, "date": 20,                      # pt
    "weather_temp": 38, "weather_place": 17,      # pt
    "status_text": 20, "hint": 17, "footer_label": 17,  # pt
    "weather_icon": 30, "status_icon": 42, "footer_icon": 28,  # px
    "footer_height": 56, "footer_pad_x": 24, "footer_gap": 18,  # px
    "top_button": 60,                             # px, the round buttons at the top right
    "pad_top": 44, "pad_side": 72, "pad_bottom": 40,  # px, around the screen
}
EDGE_MIN_SCALE, EDGE_MAX_SCALE = 0.6, 3.0
# The launcher is laid out for screens up to 1440 pixels tall. On taller ones
# (4K: 2160) all of it is drawn bigger by the same factor (1.5 in 4K), so it
# fills the screen the way it does at 1440p, with text and pictures still drawn
# at the screen's own sharpness.
ZOOM_FROM_HEIGHT = 1440
WEATHER_EVERY = 30 * 60   # seconds between weather updates
WEATHER_RETRY = 5 * 60    # ...or after a failed one


def log(*args):
    print("[launcher]", *args, file=sys.stderr, flush=True)


class ZoomBin(Gtk.Widget):
    """Shows its one child `zoom` times bigger: the child is laid out in a
    smaller space and drawn through a scale transform (focus, clicks and
    scrolling follow it)."""
    __gtype_name__ = "HtpcZoomBin"

    def __init__(self, child):
        super().__init__()
        self.zoom = 1.0
        self.child = child
        child.set_parent(self)

    def set_zoom(self, zoom):
        if abs(zoom - self.zoom) > 0.001:
            self.zoom = zoom
            self.queue_resize()

    def do_measure(self, orientation, for_size):
        z = self.zoom
        minimum, natural, _b1, _b2 = self.child.measure(orientation, -1 if for_size < 0 else int(for_size / z))
        return int(minimum * z), int(natural * z), -1, -1

    def do_size_allocate(self, width, height, baseline):
        z = self.zoom
        transform = Gsk.Transform.new().scale(z, z)
        self.child.allocate(int(width / z), int(height / z), -1, transform)

    def do_snapshot(self, snapshot):
        self.snapshot_child(self.child, snapshot)

    def do_dispose(self):
        if self.child is not None:
            self.child.unparent()
            self.child = None


# ---------------------------------------------------------------------------
# Gamepad navigation. The backend gives normalized events; this turns them into
# moves, with key repeat while a direction is held. Only acts while the launcher is in front.

class Navigator:
    DEAD_ZONE = STICK_DEAD_ZONE  # how far the stick must go to count as a press
    REPEAT_AFTER = 0.40   # holding a direction repeats after this...
    REPEAT_EVERY = 0.14   # ...at this pace
    POLL_MS = 16          # without file descriptors to wait on: read about 60 times a second
    BROKEN = GLib.IOCondition.HUP | GLib.IOCondition.ERR | GLib.IOCondition.NVAL
    DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}

    HOLD_MS = 500         # Ⓐ held this long on a light opens its settings

    def __init__(self, gamepads, active, move, press, back, other_button, blocked=lambda: False,
                 shoulder=lambda step: None, can_hold=lambda: False, long_press=lambda: None,
                 wake=lambda: False, trigger=lambda step: None):
        self.gamepads = gamepads
        self.blocked = blocked  # True while the TV is off: input is ignored (it only wakes the TV)
        self.capture = None     # set while Settings records a shortcut: gets every button event
        self.held = {}          # device -> buttons held (Start + Select + ↑/↓ is the volume)
        self.active, self.move, self.press, self.back = active, move, press, back
        self.other_button = other_button  # called with "x" or "y"
        self.shoulder = shoulder          # called with -1 (LB) or 1 (RB) when one is tapped alone
        self.tapping = None               # (device, "l1"/"r1") pressed with nothing else so far
        self.can_hold, self.long_press = can_hold, long_press
        self.wake = wake                  # a press: True when it only closed the screensaver
        self.trigger = trigger            # LT / RT: -1 / +1
        self.hold_timer = 0               # Ⓐ down on something that does more when held
        self.stick = {}         # (device, axis) -> -1 / 0 / 1
        self.direction = None   # (dx, dy) being held
        self.repeat = 0
        self.listening = False
        self.watches = {}       # fd -> GLib source: the gamepads and /dev/input, while listening
        self.timer = 0          # the polling timer instead, when the backend has no fds
        if not gamepads.available():
            log("gamepads not available (is python3-evdev installed?): keyboard only")
            return
        self.listen(True)

    def listen(self, on):
        """Read the gamepads only while the launcher is in front. Behind an app there
        is nothing for it to do (the controller service has the shortcuts)."""
        on = bool(on)
        if not self.gamepads.available() or on == self.listening:
            return
        self.listening = on
        if not on:
            self._unwatch()
            self._hold(None)
            return
        # What was pressed inside the app (A in Jellyfin...) must not act here now.
        self.gamepads.flush()
        self.held.clear()
        self.stick.clear()
        self._poll()   # also picks up gamepads plugged in meanwhile, for the top bar

    def _poll(self):
        for ev in self.gamepads.poll(0):
            self.handle(ev)
        self._watch()
        return True

    def _watch(self):
        """Have GLib wake us when a gamepad has input or one is plugged in: nothing
        runs while nobody touches the gamepad. Without file descriptors from the
        backend, read it about 60 times a second instead."""
        if not self.listening:
            return
        fds = self.gamepads.fds()
        if fds is None:
            if not self.timer:
                self.timer = GLib.timeout_add(self.POLL_MS, self._poll)
            return
        wanted = set(fds)
        for fd in [fd for fd in self.watches if fd not in wanted]:
            GLib.source_remove(self.watches.pop(fd))   # a gamepad that went away
        for fd in wanted - self.watches.keys():
            self.watches[fd] = unix_fd_add(
                GLib.PRIORITY_DEFAULT, fd, GLib.IOCondition.IN | self.BROKEN, self._readable)

    def _readable(self, fd, condition):
        self._poll()
        if condition & self.BROKEN and fd in self.watches:
            # Still there after reading it: stop watching it rather than wake up
            # again and again (the next rescan drops a gamepad that is gone).
            del self.watches[fd]
            return False
        return True

    def _unwatch(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        for source in self.watches.values():
            GLib.source_remove(source)
        self.watches.clear()

    def handle(self, ev):
        if self.capture is not None and ev.kind in ("button", "disconnected"):
            self.capture(ev)   # recording a new shortcut: buttons go there only
            return
        if home_assistant.is_press(ev, self.DEAD_ZONE) and self.active() and self.wake():
            return   # it closed the screensaver, nothing more
        if ev.kind == "button":
            held = self.held.setdefault(ev.device, set())
            (held.add if ev.value else held.discard)(ev.name)
            # LB / RB turn the page when tapped alone, on release: pressed with other
            # buttons they are a shortcut (Home + LB + RB...), and must not turn it.
            if ev.value:
                self.tapping = (ev.device, ev.name) if ev.name in ("l1", "r1") and held == {ev.name} else None
            elif self.tapping == (ev.device, ev.name):
                self.tapping = None
                if self.active() and not self.blocked():
                    self.shoulder(-1 if ev.name == "l1" else 1)
                return
            if ev.value and ({"start", "select"} <= held or "guide" in held):
                return   # a combo in progress (volume, close, home): the controller service handles it
        elif ev.kind == "disconnected":
            self.held.pop(ev.device, None)
        if home_assistant.is_press(ev, self.DEAD_ZONE) and self.blocked():
            return
        if ev.kind == "button":
            if ev.name == "a" and not ev.value and self.hold_timer:
                GLib.source_remove(self.hold_timer)   # let go before it counted as held: a press
                self.hold_timer = 0
                self.press()
            elif ev.name in self.DIRECTIONS:
                self._hold(self.DIRECTIONS[ev.name] if ev.value else None)
            elif ev.value and self.active():
                if ev.name == "a" and self.can_hold():
                    if self.hold_timer:
                        GLib.source_remove(self.hold_timer)
                    self.hold_timer = GLib.timeout_add(self.HOLD_MS, self._held)
                elif ev.name == "a":
                    self.press()
                elif ev.name == "b":
                    self.back()
                elif ev.name in ("x", "y"):
                    self.other_button(ev.name)
                elif ev.name in ("l2", "r2"):
                    self.trigger(-1 if ev.name == "l2" else 1)
        elif ev.kind == "axis":
            value = 1 if ev.value > self.DEAD_ZONE else -1 if ev.value < -self.DEAD_ZONE else 0
            key = (ev.device, ev.name)
            if self.stick.get(key, 0) == value:
                return
            self.stick[key] = value
            horizontal = ev.name == "lx"
            if value:
                self._hold((value, 0) if horizontal else (0, value))
            elif self.direction and ((horizontal and self.direction[0]) or (not horizontal and self.direction[1])):
                self._hold(None)
        elif ev.kind == "disconnected":
            for key in [k for k in self.stick if k[0] == ev.device]:
                del self.stick[key]

    def _held(self):
        self.hold_timer = 0
        self.long_press()
        return False

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


def svg_icon(name):
    """One of our own icons (launcher/icons/*.svg) as a GIcon. GTK draws a GIcon
    from the vector at the size it is shown at; Gtk.Image.set_from_file would
    rasterize the SVG at its 24 px and then stretch it (blurry on a 4K TV).
    A file of the same name in the user's icons folder (~/.config/
    htpc-launcher/icons) replaces ours, for the user's own drawings."""
    own = paths.config_dir() / "icons" / name
    return Gio.FileIcon.new(Gio.File.new_for_path(str(own if own.is_file() else ICONS / name)))


def gicon(ref):
    """Backend IconRef -> Gio icon for GTK."""
    if ref.path:
        return Gio.FileIcon.new(Gio.File.new_for_path(ref.path))
    return Gio.ThemedIcon.new_from_names(list(ref.names) or ["application-x-executable"])


# ---------------------------------------------------------------------------
# Tiles

def animate_press(button):
    """Play the "pushed" animation (button.pressed in launcher.css)."""
    button.remove_css_class("pressed")
    button.add_css_class("pressed")

    def done():
        button.remove_css_class("pressed")
        button.press_timer = 0
        return False

    if getattr(button, "press_timer", 0):
        GLib.source_remove(button.press_timer)
    button.press_timer = GLib.timeout_add(PRESS_MS, done)


def pushed(button, action):
    """Animate the push, then run the action a moment later."""
    animate_press(button)
    if PRESS_DELAY:
        GLib.timeout_add(PRESS_DELAY, lambda: action() and False)
    else:
        action()


class Tile(Gtk.Button):
    def __init__(self, app, icon, on_activate):
        super().__init__()
        self.app = app
        self.add_css_class("tile")
        self.set_focus_on_click(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_valign(Gtk.Align.CENTER)
        image = Gtk.Image.new_from_gicon(icon)
        image.set_pixel_size(128)
        image.add_css_class("tile-icon")
        name = Gtk.Label(label=app.get("name", "?"), ellipsize=Pango.EllipsizeMode.END, max_width_chars=14)
        name.add_css_class("tile-name")
        self.status = Gtk.Label(label="")
        self.status.add_css_class("tile-status")
        for w in (image, name, self.status):
            box.append(w)
        self.set_child(box)
        self.connect("clicked", lambda _b: pushed(self, lambda: on_activate(self)))

    def show_status(self, text, running=False, opening=False):
        """opening: the app was started and its window has not shown up yet
        (the tile pulses green meanwhile)."""
        self.status.set_label(text)
        for css, on in (("running", running), ("opening", opening)):
            if on:
                self.add_css_class(css)
            else:
                self.remove_css_class(css)


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
        self.connect("clicked", lambda _b: pushed(self, on_activate))


# ---------------------------------------------------------------------------
# The launcher window

PAD_ICONS = ("xbox", "playstation", "generic")   # a Nintendo pad gets the plain drawing


class Launcher(HomeMixin, EditorMixin, SettingsMixin, ScreensaverMixin):
    gicon = staticmethod(gicon)  # the editor turns backend icons into GTK icons with it
    svg_icon = staticmethod(svg_icon)

    def __init__(self, gtk_app):
        self.gtk_app = gtk_app
        self.cfg, migrated = config.load(fallback=True)   # a broken apps.json: the last good copy
        if migrated:
            config.save(self.cfg)
            log("apps.json converted to the current format")
        self.t = Translator(self.cfg.get("language"))
        backend = get_backend()
        self.windows = backend.window_control()
        self.apps = backend.apps()
        self.system = backend.system()
        self.bluetooth = backend.bluetooth()
        self.display = backend.display()
        self.audio = backend.audio()
        self.display_app_until = 0.0     # an app's own resolution: don't go back to the default before this
        self.display_changed = True      # check once at start (a mode left over from before)
        self.app_icons_dir = paths.app_icons_dir()

        # Background color: its own CSS provider, above launcher.css, so it can change live.
        self.theme_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.theme_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.apply_theme(self.cfg.get("background", themes.DEFAULT_THEME))

        # Edge sizes follow the screen size: their own provider, above launcher.css.
        self.edge_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.edge_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        self.edge_scale = None
        self.screen_size = None

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for folder in self.apps.icon_dirs():
            theme.add_search_path(folder)
        self.opening = {}         # app id -> when it was started (None once its window showed up)
        self.woken = {}           # Wake-on-LAN target -> when it was last sent
        self.overlays = []        # stack of things shown on top (confirmation, editor...)
        self.editing = False
        self.tiles, self.add_tile, self.tile_rows = [], None, []
        self.weather_fetch = weather.http_json  # the tests swap this for a fake
        self.conditions = None    # last weather that arrived (kept when an update fails)
        self.weather_timer = 0
        self.last_kind = "wifi"   # connection kind, for the "no connection" icon

        self.win = Gtk.Window(application=gtk_app, title="HTPC")
        self.win.add_css_class("htpc")
        self.win.set_default_size(1920, 1080)

        self.overlay = Gtk.Overlay()
        self.zoom_bin = ZoomBin(self.overlay)
        self.win.set_child(self.zoom_bin)
        self.build_ui()

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.win.add_controller(keys)

        self.win.connect("notify::is-active", self._active_changed)
        self.win.connect("notify::focus-widget", self._focus_moved)

        self.navigator = Navigator(backend.gamepads(), self.win.is_active, self.move, self.press,
                                   self.back, self.other_button, blocked=home_assistant.input_blocked,
                                   shoulder=self.shoulder, can_hold=self.can_hold,
                                   long_press=self.long_press, wake=self.wake, trigger=self.switch_tab)
        self.gamepads = self.navigator.gamepads

        GLib.timeout_add_seconds(1, self._update_clock)
        self.network = Gio.NetworkMonitor.get_default()
        self.network.connect("notify::connectivity", lambda *_: self._update_network())
        self.network.connect("network-changed", lambda *_: self._update_network())
        # These read D-Bus and sysfs for the top bar, which can't be seen behind an
        # app: they skip their work there, and _active_changed catches up on return.
        GLib.timeout_add_seconds(5, self._in_front(self._update_network))
        GLib.timeout_add_seconds(1, self._in_front(self._update_gamepads))
        GLib.timeout_add_seconds(1, lambda: self.opening and self._check_opening() or True)
        GLib.timeout_add_seconds(3, self._every_3s)
        self.start_screensaver_timer()
        GLib.timeout_add(500, self._check_screen_size)
        GLib.timeout_add_seconds(HOUSE_EVERY, self._home_tick)
        self.refresh_top_bar()
        self.update_weather()
        self.update_media(force=True)
        self.update_house()

        self.win.set_cursor(Gdk.Cursor.new_from_name("none", None))
        self.win.fullscreen()
        self.win.present()
        if self.tiles:
            self.tiles[0].grab_focus()

    def build_ui(self):
        """(Re)build everything on screen in the current language. Called again
        when the language changes; the timers keep working on the new widgets."""
        self.footer_images = []
        recent, house = getattr(self, "recent_items", []), getattr(self, "house_data", None)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("root")
        root.append(self._top_bar())
        root.append(self._home_body())
        root.append(self._footer())
        self.overlay.set_child(root)
        self.build_grid()
        if recent:
            self._show_recent(recent)
        if house:
            self._show_house(house)

    # --- sizes that follow the screen -----------------------------------------------

    def px(self, key):
        return max(1, round(EDGE[key] * (self.edge_scale or 1.0)))

    def _check_screen_size(self):
        w, h = self.win.get_width(), self.win.get_height()
        if w > 0 and h > 0 and (w, h) != self.screen_size:
            self.screen_size = (w, h)
            zoom = max(1.0, h / ZOOM_FROM_HEIGHT)
            self.zoom_bin.set_zoom(zoom)
            w, h = w / zoom, h / zoom   # the space the launcher is laid out in
            self.apply_edge_scale(max(EDGE_MIN_SCALE, min(EDGE_MAX_SCALE, min(w / 1920, h / 1080))))
            if zoom > 1:
                log(f"screen {self.screen_size}: everything drawn {zoom:.2f}x, laid out in {w:.0f}x{h:.0f}")
        return True

    def apply_edge_scale(self, scale):
        """Resize the clock, weather, status, hint and footer for this screen."""
        self.edge_scale = scale
        e = {k: v * scale for k, v in EDGE.items()}
        css = f"""
            .root {{ padding: {e['pad_top']:.0f}px {e['pad_side']:.0f}px {e['pad_bottom']:.0f}px {e['pad_side']:.0f}px; }}
            .clock {{ font-size: {e['clock']:.1f}pt; }}
            .date {{ font-size: {e['date']:.1f}pt; }}
            .weather-temp {{ font-size: {e['weather_temp']:.1f}pt; }}
            .weather-place {{ font-size: {e['weather_place']:.1f}pt; }}
            .network, .gamepad-count {{ font-size: {e['status_text']:.1f}pt; }}
            .hint {{ font-size: {e['hint']:.1f}pt; }}
            .footer-button-label {{ font-size: {e['footer_label']:.1f}pt; }}
            button.footer-button {{ min-height: {e['footer_height']:.0f}px;
                                    padding: 4px {e['footer_pad_x']:.0f}px; }}
            .footer {{ border-spacing: {e['footer_gap']:.0f}px; }}
            button.top-button {{ min-width: {e['top_button']:.0f}px; min-height: {e['top_button']:.0f}px; }}
        """
        if hasattr(self.edge_provider, "load_from_string"):  # GTK 4.12+
            self.edge_provider.load_from_string(css)
        else:
            self.edge_provider.load_from_data(css, -1)
        for image in self.footer_images:
            image.set_pixel_size(self.px("footer_icon"))
        self.weather_icon.set_pixel_size(self.px("weather_icon"))
        self.net_icon.set_pixel_size(self.px("status_icon"))
        self.pads_state = None
        self._update_gamepads()
        log(f"screen {self.screen_size}: edge scale {scale:.2f}")

    def refresh_top_bar(self):
        self._update_clock()
        self._update_network()
        self.pads_state = None
        self._update_gamepads()
        self.show_weather()

    def hint_text(self):
        current = shortcuts.combos(self.cfg)
        return self.t("hint_normal", home=shortcuts.combo_label(current["home"]),
                      close=shortcuts.combo_label(current["close"]))

    def tv_off_available(self):
        """The power menu offers "Turn off the TV" when Home Assistant is set up
        (its webhook is what turns the TV off)."""
        return bool(home_assistant.webhook_url(self.cfg))

    @property
    def rows(self):
        """Top to bottom: settings and the power menu, the media tabs and their row,
        the apps, the house."""
        return [self.top_buttons, self.tab_row, self.recent_row] + self.tile_rows + self.house_rows

    @property
    def top_buttons(self):
        return [b for b in (self.btn_source, self.btn_settings, self.btn_power) if b.get_visible()]

    # --- the TV input button ---------------------------------------------------------

    def quick_source(self):
        """The input the top button switches the TV to, or None when not set up."""
        ha = self.cfg.get("home_assistant") or {}
        source = (ha.get("quick_source") or {}).get("source")
        return source if source and home_assistant.api_ready(self.cfg) else None

    def refresh_source_button(self):
        source = self.quick_source()
        self.btn_source.set_visible(bool(source))
        if source:
            label = (self.cfg["home_assistant"].get("quick_source") or {}).get("label") or source
            self.btn_source.update_property([Gtk.AccessibleProperty.LABEL], [self.t("switch_to", source=label)])

    def switch_tv_source(self):
        """Switch the TV to the other input. The first time, the HTPC's own input is
        remembered, so the HTPC's gamepads can bring the TV back (see home_assistant)."""
        source = self.quick_source()
        if not source:
            return
        cfg, get, post = dict(self.cfg), getattr(self, "ha_get", None), getattr(self, "ha_api_post", None)

        def job():
            home = cfg["home_assistant"].get("htpc_source")
            current, sources = home_assistant.tv_sources(cfg, get)
            if not home or (sources and home not in sources):   # never set, or the TV renamed it
                home = current if current and current != source else None
            home_assistant.switch_source(cfg, source, post)
            return home

        def done(result):
            if isinstance(result, Exception):
                self._message(self.t("switch_failed", error=self._reason(result)))
                return
            ha = self.cfg.get("home_assistant") or {}
            if result and ha.get("htpc_source") != result:
                self.cfg["home_assistant"] = {**ha, "htpc_source": result}
                self.save_config()
            log("tv switched to", source)

        in_background(job, done)

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

        self.tiles = [Tile(a, self.icon_for(a), self.on_tile) for a in self.cfg.get("apps", [])]
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

    def icon_for(self, app):
        return gicon(self.apps.icon_for(app))

    def save_config(self):
        config.save(self.cfg)
        log("apps.json saved")

    # --- top bar ---------------------------------------------------------------

    def _top_bar(self):
        """Weather on the left, clock in the middle, gamepads and network on the right.
        A CenterBox keeps the clock centered whatever the sides hold."""
        bar = Gtk.CenterBox()
        bar.add_css_class("top-bar")

        # Weather: "● 24°" and its icon, on the date's line and in its style.
        # Hidden until a location is set and the first answer arrives.
        self.weather_box = Gtk.Box(spacing=10, valign=Gtk.Align.CENTER)
        self.weather_box.add_css_class("weather")
        dot = Gtk.Label(label="•")
        dot.add_css_class("date")
        dot.add_css_class("weather-dot")
        self.weather_temp = Gtk.Label(label="", xalign=0)
        self.weather_temp.add_css_class("date")
        self.weather_icon = Gtk.Image()
        self.weather_icon.set_pixel_size(self.px("weather_icon"))
        for w in (dot, self.weather_temp, self.weather_icon):
            self.weather_box.append(w)
        self.weather_place = Gtk.Label(label="")   # kept for Settings; not on screen
        self.weather_box.set_visible(False)

        clock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        self.time_label = Gtk.Label(label="")
        self.time_label.add_css_class("clock")
        self.date_label = Gtk.Label(label="")
        self.date_label.add_css_class("date")
        date_line = Gtk.Box(spacing=16)
        date_line.append(self.date_label)
        date_line.append(self.weather_box)
        clock.append(self.time_label)
        clock.append(date_line)

        # Connected: just the icon. Text only when something is wrong.
        net = Gtk.Box(spacing=10, valign=Gtk.Align.START)
        net.add_css_class("network")
        self.net_text = Gtk.Label(label="")
        self.net_icon = Gtk.Image()
        self.net_icon.set_pixel_size(self.px("status_icon"))

        # Gamepads: one drawing per connected gamepad (an Xbox-style one, a
        # PlayStation-style one, or a plain one), its battery bar under it.
        # Nothing at all when none is connected.
        self.pads_box = Gtk.Box(spacing=18, valign=Gtk.Align.CENTER)
        self.pads_box.add_css_class("gamepads")
        self.pads_box.set_margin_end(14)
        self.pads_state = None
        net.append(self.pads_box)
        net.append(self.net_text)
        net.append(self.net_icon)

        # Left: the clock, the date and the weather. Right: status, settings and the power menu.
        self.time_label.set_xalign(0)
        self.date_label.set_xalign(0)
        left = Gtk.Box(valign=Gtk.Align.START)
        left.append(clock)
        # The TV input button (a console on HDMI 2...), when one is set up.
        self.btn_source = self._top_button("console.svg", self.t("switch_input"), self.switch_tv_source)
        self.btn_settings = self._top_button("settings.svg", self.t("settings"), self.settings_button)
        self.btn_power = self._top_button("power.svg", self.t("power_menu"), self.power_menu)
        buttons = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        buttons.add_css_class("top-buttons")
        for b in (self.btn_source, self.btn_settings, self.btn_power):
            buttons.append(b)
        self.refresh_source_button()
        net.set_valign(Gtk.Align.CENTER)
        right = Gtk.Box(spacing=32, valign=Gtk.Align.START)
        right.append(net)
        right.append(buttons)

        bar.set_start_widget(left)
        bar.set_end_widget(right)
        return bar

    # --- footer ----------------------------------------------------------------

    def _footer(self):
        """Only shown in edit mode, to say how it works. (The button and shortcut
        hints it used to show all the time are gone: see docs/gamepads.md.)"""
        bar = Gtk.CenterBox()
        bar.add_css_class("footer-bar")
        self.hint = Gtk.Label(label=self.hint_text(), xalign=0, valign=Gtk.Align.CENTER)
        self.hint.add_css_class("hint")
        self.hint.set_visible(self.editing)
        bar.set_start_widget(self.hint)
        return bar

    def _top_button(self, icon, text, action):
        """A round icon button for the top right. Its label is only shown when it
        says something the icon can't (the gear reads "Done" in edit mode)."""
        b = self._footer_button(icon, text, action)
        b.remove_css_class("footer-button")
        b.add_css_class("top-button")
        b.label.set_visible(False)
        b.get_child().set_halign(Gtk.Align.CENTER)   # the icon in the middle of the circle
        b.get_child().set_valign(Gtk.Align.CENTER)
        b.update_property([Gtk.AccessibleProperty.LABEL], [text])
        return b

    def turn_tv_off(self):
        """Asks Home Assistant to turn the TV off (the "tv_off" webhook event), and
        puts the launcher back on its start: menus closed, the first app selected,
        scrolled to the top. Any gamepad button wakes the TV again through the
        same automation."""
        log("asking Home Assistant to turn the TV off")
        home_assistant.turn_tv_off(self.cfg)
        self.go_home()
        if self.cfg.get("tv_off_gamepads", True):
            # A moment later, so the press on the menu has been let go of.
            GLib.timeout_add(1500, lambda: (self._gamepads_off(), False)[1])

    def _gamepads_off(self):
        """Bluetooth gamepads off with the TV (Settings → Gamepads). Their home
        button turns them on; reconnecting wakes the TV through Home Assistant."""
        in_background(self.bluetooth.disconnect_gamepads,
                      lambda r: log("gamepads off with the TV:", r if not isinstance(r, Exception) else repr(r)))

    def go_home(self):
        while self.overlays:
            self.pop_overlay()
        if self.editing:
            self.toggle_edit_mode()
        (self.tiles[0] if self.tiles else self.btn_settings).grab_focus()
        self._scroll_to(0.0)

    def _footer_button(self, icon, text, action):
        b = Gtk.Button()
        b.add_css_class("footer-button")
        b.set_focus_on_click(False)
        box = Gtk.Box(spacing=8)
        image = Gtk.Image.new_from_gicon(svg_icon(icon))
        image.set_pixel_size(self.px("footer_icon"))
        image.add_css_class("footer-icon")
        self.footer_images.append(image)
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
        self.date_label.set_label(self.t.date(now.get_day_of_week(), now.get_day_of_month(), now.get_month(),
                                              now.get_year()))
        return True

    def _update_network(self):
        """Icon by how we are connected (cable or Wi-Fi), color by whether the internet works."""
        c = self.network.get_connectivity()
        kind = self.system.connection_kind()
        if kind:
            self.last_kind = kind
        if not self.network.get_network_available() or c == Gio.NetworkConnectivity.LOCAL:
            text, state = self.t("no_internet"), "off"
        elif c == Gio.NetworkConnectivity.FULL:
            text, state = "", "on"
        else:  # LIMITED or PORTAL
            text, state = self.t("limited_internet"), "limited"
        # Without a connection the OS reports no kind: keep showing the last one, crossed out.
        icon = (kind or self.last_kind) + {"on": "", "limited": "-limited", "off": "-off"}[state]
        self.net_icon_name = icon
        self.net_icon.set_from_gicon(svg_icon(f"{icon}.svg"))
        self.net_icon.set_pixel_size(self.px("status_icon"))
        self.net_text.set_label(text)
        self.net_text.set_visible(bool(text))
        for s in ("on", "off", "limited"):
            self.net_text.remove_css_class(s)
        self.net_text.add_css_class(state)
        changed = getattr(self, "network_state", None) not in (None, state)
        self.network_state = state
        self.network_kind = kind or self.last_kind
        if changed and state == "on" and self.cfg.get("weather") and not self.conditions:
            self.update_weather()  # internet came back: no need to wait for the retry
        return False

    def _check_opening(self):
        """An app counts as "opening" until its window shows up. Checked even while
        the launcher is behind it, so an app closed soon after opening does not
        come back as "opening…"."""
        running = self._running_ids() if self.opening else set()
        for app_id in list(self.opening):
            if app_id.lower() in running:
                self.opening[app_id] = None  # seen: no longer opening
            elif self.opening[app_id] is None:
                del self.opening[app_id]     # seen and now closed
            elif time.monotonic() - self.opening[app_id] >= OPENING_GRACE:
                del self.opening[app_id]     # never showed up
        return True

    @staticmethod
    def battery_percent(battery):
        """0..100 for the bar; a level without a number becomes a rough one."""
        if battery.percent is not None:
            return max(0, min(100, battery.percent))
        return {"full": 100, "high": 75, "normal": 50, "low": 20, "critical": 5}.get(battery.level, 50)

    def _set_button_style(self, pads):
        """Name the buttons as the pads in use label them: △ ○ ✕ □ when every
        connected gamepad is a PlayStation one, Ⓐ Ⓑ Ⓧ Ⓨ otherwise."""
        style = "playstation" if pads and all(p.kind == "playstation" for p in pads) else "xbox"
        if style == self.t.buttons:
            return
        self.t.buttons = style
        self.hint.set_label(self.t("hint_edit") if self.editing else self.hint_text())
        if getattr(self, "house_data", None) is not None:
            self._show_house(self.house_data)
        if self.available_tabs():
            self.media_note.set_label(self._media_note())
            self.page_hint.set_label(self._page_hint())

    def _update_gamepads(self):
        """One drawing per connected gamepad, its battery under it. The list is kept
        up to date by the Navigator (it reads the gamepads)."""
        pads = self.gamepads.pads()
        self._set_button_style(pads)
        if self.pads_state is not None and len(pads) > len(self.pads_state):
            self.pad_connected()
        state = tuple((p.kind, p.name, None if p.battery is None else
                       (self.battery_percent(p.battery), p.battery.charging)) for p in pads)
        if state == self.pads_state:
            return True
        self.pads_state = state
        child = self.pads_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.pads_box.remove(child)
            child = following
        size = round(self.px("status_icon") * 1.3)   # big enough to tell the kinds apart
        for pad in pads[:4]:
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, valign=Gtk.Align.CENTER)
            column.add_css_class("pad")
            image = Gtk.Image.new_from_gicon(svg_icon(f"pad-{pad.kind if pad.kind in PAD_ICONS else 'generic'}.svg"))
            image.set_pixel_size(size)
            column.append(image)
            bar = Gtk.LevelBar(min_value=0, max_value=100)
            bar.set_size_request(size, 7)
            bar.add_css_class("pad-battery")
            for name in ("low", "high", "full"):
                bar.remove_offset_value(name)
            if pad.battery is None:
                bar.set_value(100)
                bar.add_css_class("wired")        # on a cable: a full, plain bar
                tip = pad.name
            else:
                pct = self.battery_percent(pad.battery)
                bar.set_value(pct)
                bar.add_css_class("charging" if pad.battery.charging else
                                  "low" if pct < 20 else "half" if pct < 50 else "ok")
                tip = f"{pad.name}: {pct}%"
            column.set_tooltip_text(tip)
            column.update_property([Gtk.AccessibleProperty.LABEL], [tip])
            column.append(bar)
            self.pads_box.append(column)
        self.pads_box.set_visible(bool(pads))
        return True

    # --- weather -------------------------------------------------------------------

    def update_weather(self):
        """Ask for the weather in a thread; the answer comes back on the GTK thread."""
        if self.weather_timer:
            GLib.source_remove(self.weather_timer)
            self.weather_timer = 0
        place = self.cfg.get("weather")
        if not place:
            self.conditions = None
            self.show_weather()
            return False
        unit = self.cfg.get("temperature_unit", "celsius")
        fetch = self.weather_fetch
        # Any failure just means "try later" (_weather_arrived gets the exception).
        in_background(lambda: weather.current(place["latitude"], place["longitude"], unit, fetch),
                      lambda result: self._weather_arrived(place, unit, result))
        return False

    def _weather_arrived(self, place, unit, result):
        if place is not self.cfg.get("weather") or unit != self.cfg.get("temperature_unit", "celsius"):
            return False  # the settings changed meanwhile; a newer request is on its way
        if isinstance(result, Exception):
            log("weather not updated:", result)
            delay = WEATHER_RETRY
        else:
            self.conditions = result
            delay = WEATHER_EVERY
        self.show_weather()
        self.weather_timer = GLib.timeout_add_seconds(delay, self.update_weather)
        return False

    def show_weather(self):
        place, c = self.cfg.get("weather"), self.conditions
        self.show_forecast(c if place else None)
        if not place or not c:
            self.weather_box.set_visible(False)
            return
        self.weather_icon.set_from_gicon(svg_icon(c.icon))
        self.weather_icon.set_pixel_size(self.px("weather_icon"))
        self.weather_temp.set_label(f"{c.temperature}°")
        self.weather_place.set_label(place.get("name", ""))
        self.weather_box.set_visible(True)

    def _in_front(self, job):
        """A timer callback that only does `job` while the launcher is in front."""
        def tick():
            if self.win.is_active():
                job()
            return True
        return tick

    def _active_changed(self, *_):
        active = self.win.is_active()
        if not hasattr(self, "navigator"):
            return   # still being built
        self.navigator.listen(active)
        self.last_input = time.monotonic()   # the wait for the screensaver starts again
        if active:
            self.refresh_status()
            self.restore_display()
            self._update_gamepads()
            self._update_network()
            self.refresh_resume()
            self._home_tick()

    def _every_3s(self):
        if self.win.is_active() and not self.overlays:
            self.refresh_status()
        if self.win.is_active():
            self.restore_display()
        return True

    # --- per-app resolution --------------------------------------------------------

    def use_display_mode(self, key):
        """Switch the screen to an apps.json mode key ("3840x2160@30"), or to the
        default with None. Nothing happens when it is already there or can't be done."""
        try:
            modes = self.display.modes()
            target = pick_mode(modes, key) if key else self.display.default_mode()
            if target is None:
                if key:
                    log("no", key, "mode on this screen")
                return False
            if target.current:
                return False
            log("display:", target.label())
            self.display.apply(target)
            return True
        except Exception as e:  # noqa: BLE001 - no Mutter, refused...
            log("could not change the resolution:", e)
            return False

    def restore_display(self):
        """The launcher is in front: the default resolution, unless an app just asked for its own."""
        if not self.display_changed or time.monotonic() < self.display_app_until:
            return
        self.display_changed = False
        self.use_display_mode(None)

    # --- apps --------------------------------------------------------------------

    def _running_ids(self):
        """Every name the open windows answer to, from one ListWindows call (instead
        of one IsRunning per app on the GTK thread)."""
        try:
            windows = self.windows.windows() or []
        except Exception as e:  # noqa: BLE001 - the extension is not answering
            log("could not list the windows:", e)
            windows = []
        names = set()
        for w in windows:
            names.update(i.lower() for i in w.ids)
            names.add((w.app_id or "").lower())
        return names

    def refresh_status(self):
        now = time.monotonic()
        running = set() if self.editing else self._running_ids()
        for tile in self.tiles:
            if self.editing:
                tile.show_status(self.t("status_edit"))
                continue
            app_id = tile.app["id"]
            if app_id.lower() in running:
                self.opening.pop(app_id, None)
                tile.show_status(self.t("status_open"), running=True)
            elif self.opening.get(app_id) is not None and now - self.opening[app_id] < OPENING_GRACE:
                tile.show_status(self.t("status_opening"), running=True, opening=True)
            else:
                self.opening.pop(app_id, None)
                tile.show_status("")
        return False

    def _spawn(self, command):
        return self.system.spawn(command)

    WAKE_AGAIN_S = 60    # the same PC is woken at most once a minute

    def wake_pc_for(self, app):
        """The app's "wake_on_lan" (a Home Assistant Wake-on-LAN button or a MAC):
        wakes the computer it streams from, in the background."""
        target = (app or {}).get("wake_on_lan")
        ha = self.cfg.get("home_assistant") or {}
        if not target or not (ha.get("enabled", True) and ha.get("url") and ha.get("token")):
            return
        now = time.monotonic()
        if now - self.woken.get(target, -self.WAKE_AGAIN_S) < self.WAKE_AGAIN_S:
            return
        self.woken[target] = now
        cfg, post = dict(self.cfg), getattr(self, "ha_api_post", None)

        def done(result):
            if isinstance(result, Exception):
                log("wake on LAN failed:", result)
                self.woken.pop(target, None)
            else:
                log("wake on LAN sent:", target)

        in_background(lambda: home_assistant.wake_on_lan(cfg, target, post), done)

    def open_app(self, tile):
        app = tile.app
        app_id = app["id"]
        self.wake_pc_for(app)
        # The app's own resolution (or the default) before its window shows up.
        mode = app.get("display_mode")
        if self.use_display_mode(mode) or mode:
            self.display_changed = True
            if mode:
                self.display_app_until = time.monotonic() + DISPLAY_APP_GRACE
        windows = app.get("preferred_windows")
        if app.get("fullscreen", True):
            # Covers both cases: an open window goes full screen now, a new one when it appears.
            self.windows.fullscreen_on_open(app_id, FULLSCREEN_FOR)
        if self.windows.activate(app_id, windows):
            log("resuming", app["name"])
            on_resume = app.get("on_resume")
            if on_resume and self._spawn(on_resume):
                # e.g. Steam switching to Big Picture opens a new window; bring it up.
                GLib.timeout_add(RESUME_DELAY, lambda: self.windows.activate(app_id, windows) and False)
            return
        started = self.opening.get(app_id)
        if started is not None and time.monotonic() - started < OPENING_GRACE:
            log(app["name"], "is still opening")
            return
        command = app.get("launch")
        if not command:
            log("no launch command for", app["name"])
            return
        log("starting", app["name"], command)
        if self._spawn(command):
            self.opening[app_id] = time.monotonic()
            tile.show_status(self.t("status_opening"), running=True, opening=True)

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
        # Long titles (an error message) wrap instead of running off the screen.
        label = Gtk.Label(label=title, wrap=True, max_width_chars=44, justify=Gtk.Justification.CENTER)
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

    # --- the power menu: TV off, restart, shut down ------------------------------------

    def _menu_option(self, icon, text, action, danger=False):
        b = Gtk.Button()
        b.add_css_class("dialog-button")
        b.add_css_class("menu-option")
        if danger:
            b.add_css_class("danger")
        b.set_focus_on_click(False)
        box = Gtk.Box(spacing=20)
        image = Gtk.Image.new_from_gicon(svg_icon(icon))
        image.set_pixel_size(34)
        b.label = Gtk.Label(label=text, xalign=0)
        box.append(image)
        box.append(b.label)
        b.set_child(box)
        b.connect("clicked", lambda _b: action())
        return b

    def power_menu(self):
        """The power button: turn off the TV (with Home Assistant), restart or shut
        down the computer. The menu itself is the confirmation: the selection
        starts on the TV (or on Cancel), never on restart or shut down."""
        box = self.dialog_box(self.t("power_menu"))
        options = []
        if self.tv_off_available():
            options.append(self._menu_option("tv-off.svg", self.t("tv_off"), self.turn_tv_off))
        options.append(self._menu_option("restart.svg", self.t("restart_computer"),
                                         lambda: self._run_power("restart"), danger=True))
        options.append(self._menu_option("power.svg", self.t("power_off_computer"),
                                         lambda: self._run_power("power_off"), danger=True))
        cancel = self.dialog_button(self.t("cancel"), self.pop_overlay)
        for b in options:
            box.append(b)
        box.append(cancel)
        self.power_options = options
        self.push_overlay(box, [[b] for b in options] + [[cancel]],
                          focus=options[0] if self.tv_off_available() else cancel)

    def _run_power(self, action):
        """Restart or shut down, from a thread: the answer can take a moment, and
        when the machine won't go down, the reason shows on screen."""
        self.pop_overlay()
        log("power:", action)
        job = self.system.reboot if action == "restart" else self.system.power_off

        def done(result):
            if isinstance(result, Exception):
                log("power failed:", result)
                self._message(self.t("power_failed", error=str(result)[:300]))

        in_background(job, done)

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
        if not isinstance(focused, Gtk.Button):
            return
        if self.overlays and not focused.is_ancestor(self.overlays[-1]["backdrop"]):
            return   # the focus is still on something under a box (e.g. "Installing…"): not pressable
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
        elif not self.overlays and name == "y" and self.can_hold():
            self.open_light(self.win.get_focus())

    def _on_key(self, _ctl, keyval, _code, _mods):
        if self.wake():
            return True   # it closed the screensaver
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
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
            self.shoulder(1 if keyval == Gdk.KEY_Page_Down else -1)
        else:
            return False
        return True


def _drop_no_portals():
    parts = [p for p in os.environ.get("GDK_DEBUG", "").split(",") if p and p != "no-portals"]
    if parts:
        os.environ["GDK_DEBUG"] = ",".join(parts)
    else:
        os.environ.pop("GDK_DEBUG", None)


def main():
    if not config.exists():
        raise SystemExit(f"Missing configuration file: {paths.config_file()}")

    # Is a launcher already open? Then just bring it to the front.
    if get_backend().window_control().activate(LAUNCHER_ID):
        log("already running")
        return

    app = Gtk.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
    state = {}

    def activate(a):
        if "launcher" in state:
            return
        _drop_no_portals()
        provider = Gtk.CssProvider()
        provider.load_from_path(str(CSS))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        state["launcher"] = Launcher(a)

    app.connect("activate", activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
