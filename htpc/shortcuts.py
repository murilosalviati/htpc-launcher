# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""What the gamepad shortcuts do, independent of the operating system.

  * Home combo (Guide + L1 + R1 by default): pauses media if the focused app
    has "pause_on_home", then shows the launcher. The app keeps running behind
    it. The guide button alone is left to the apps (Steam opens its menu with it).
  * Close combo (Start + Select + L1 + R1 by default): closes the focused app
    and returns to the launcher.
  * Volume: Start + Select + Up / Down raise or lower the output volume by 5
    points (holding it keeps going), with GNOME's volume indicator on screen. Apps with "close_on_second_press" (Moonlight) get the first
    press themselves (it ends the stream); a second press within 15 s closes them.

The controller service feeds normalized gamepad events into GamepadShortcuts;
Shortcuts does the work through the backend.
"""

import logging
import threading
import time

from . import config
from .timing import Throttle

# Both combos can be changed in Settings → Gamepad shortcuts ("shortcuts" in apps.json).
DEFAULT_COMBOS = {
    "home": frozenset({"guide", "l1", "r1"}),
    "close": frozenset({"start", "select", "l1", "r1"}),
}
CLOSE_COMBO = DEFAULT_COMBOS["close"]
# Buttons a combo may use (the d-pad is for moving around).
COMBO_BUTTONS = ("guide", "start", "select", "l1", "r1", "a", "b", "x", "y")
# Volume: fixed combos. A custom combo can't be just Start + Select (it would fire with these).
VOLUME_COMBOS = {"up": frozenset({"start", "select", "up"}), "down": frozenset({"start", "select", "down"})}
VOLUME_STEP = 0.05
REPEAT_DELAY = 0.45     # holding the volume combo: first repeat after this
REPEAT_EVERY = 0.12     # then this often
# How they are written on screen, Xbox style (PlayStation: PS, Options, Share,
# L1, R1, ✕ ○ □ △; Nintendo: Home, +, -, L, R).
BUTTON_LABELS = {"guide": "Home", "start": "Start", "select": "Select", "l1": "LB", "r1": "RB",
                 "a": "A", "b": "B", "x": "X", "y": "Y"}

# Steam creates a virtual gamepad that repeats the real gamepad's events;
# an action inside this interval is treated as a repeat and ignored.
MIN_INTERVAL = 1.0
SECOND_PRESS_WINDOW = 15.0    # close_on_second_press: time allowed for the 2nd press
DEFAULT_CLOSE_TIMEOUT = 3.0   # how long to wait for an app to close before forcing it

log = logging.getLogger("htpc-controller")


def combo_problem(combo, other):
    """Why a combo can't be used next to the other one, or None if it can."""
    if len(combo) < 2:
        return "too_short"
    if not set(combo) <= set(COMBO_BUTTONS):
        return "bad_button"
    if set(combo) <= set(other) or set(other) <= set(combo):
        return "overlap"   # pressing one would also fire the other
    if any(set(combo) <= v for v in VOLUME_COMBOS.values()):
        return "volume"    # Start + Select would fire on the way to the volume combos
    return None


def combos(cfg):
    """{"home": frozenset, "close": frozenset}: the ones in apps.json when valid,
    otherwise the defaults."""
    saved = (cfg or {}).get("shortcuts") or {}
    result = dict(DEFAULT_COMBOS)
    for name in result:
        value = saved.get(name)
        if isinstance(value, list) and value:
            result[name] = frozenset(value)
    if combo_problem(result["home"], result["close"]) or combo_problem(result["close"], result["home"]):
        log.warning("shortcuts in apps.json are not usable together; using the defaults")
        return dict(DEFAULT_COMBOS)
    return result


def combo_label(combo):
    """"Home + LB + RB", in a fixed order."""
    return " + ".join(BUTTON_LABELS[b] for b in COMBO_BUTTONS if b in combo)


def app_ids(app):
    """Every lowercase name an apps.json entry answers to. Tolerates hand-edited
    entries (no "id", "extra_ids": null or a string)."""
    if not isinstance(app, dict):
        return []
    extra = app.get("extra_ids") or []
    if isinstance(extra, str):
        extra = [extra]
    names = [app.get("id"), *(extra if isinstance(extra, (list, tuple)) else [])]
    return [i.lower() for i in names if isinstance(i, str) and i]


def app_for_window(cfg, window):
    """The apps.json entry that owns a window (by the names the backend reports)."""
    names = set(window.ids) | {(window.app_id or "").lower()}
    apps = cfg.get("apps") if isinstance(cfg, dict) else None
    for app in apps if isinstance(apps, list) else []:
        if names & set(app_ids(app)):
            return app
    return None


def is_launcher(cfg, window):
    launcher = cfg.get("launcher") if isinstance(cfg, dict) else None
    lid = str((launcher if isinstance(launcher, dict) else {}).get("id") or "htpc-launcher").lower()
    return lid in window.ids or window.app_id.lower() == lid


class Shortcuts:
    def __init__(self, backend):
        self.backend = backend
        self.system = backend.system()
        self.media = backend.media()
        self._windows = None
        self.action = Throttle(MIN_INTERVAL)   # Steam's virtual pad may repeat a combo
        self.first_press = 0.0

    @property
    def windows(self):
        if self._windows is None:
            self._windows = self.backend.window_control()
        return self._windows

    def settings(self):
        """apps.json, or the last one that could be read (a broken file must not
        stop the shortcuts)."""
        try:
            cfg = config.load()[0]
            if not isinstance(cfg, dict):
                raise ValueError("apps.json is not an object")
            self._last_cfg = cfg
        except Exception as e:  # noqa: BLE001 - JSON error, missing file...
            log.error("could not read apps.json (%s); using the last good one", e)
            cfg = getattr(self, "_last_cfg", None) or {}
        return cfg

    def _context(self, windows=None):
        """(config, focused window); the window is None if the OS side did not answer."""
        cfg = self.settings()
        try:
            window = (windows or self.windows).focused()
        except Exception as e:
            log.error("window control did not answer: %s", e)
            if windows is None:
                self._windows = None  # reconnect next time
            return cfg, None
        return cfg, window

    def _show_launcher(self, cfg, windows):
        if windows.show_launcher():
            return
        command = cfg.get("launcher", {}).get("launch")
        if command:
            log.info("launcher was not running; starting it")
            self.system.spawn(command)
        else:
            log.warning("launcher is not running and there is no command to start it")

    def volume(self, direction):
        """direction +1 or -1: one step, and the level on screen."""
        try:
            result = self.system.change_volume(direction * VOLUME_STEP)
        except Exception as e:  # noqa: BLE001 - no audio server, wpctl failed...
            log.warning("volume: %s", e)
            return
        if result is None:
            return
        level, muted = result
        if muted or level <= 0:
            icon = "audio-volume-muted-symbolic"
        elif level < 0.34:
            icon = "audio-volume-low-symbolic"
        elif level < 0.67:
            icon = "audio-volume-medium-symbolic"
        else:
            icon = "audio-volume-high-symbolic"
        log.info("volume %s: %d%%%s", "up" if direction > 0 else "down", round(level * 100),
                 " (muted)" if muted else "")
        try:
            if not self.windows.show_osd(icon, level):
                self._windows = None   # older extension: no indicator, the volume changed anyway
        except Exception as e:  # noqa: BLE001
            log.debug("volume indicator: %s", e)

    def guide(self):
        if not self.action.ready():
            return
        # Asking GNOME and pausing players can take a moment (a stuck player waits
        # for its timeout): not on the thread that reads the gamepads.
        threading.Thread(target=self._guide, daemon=True).start()

    def _guide(self):
        try:
            windows = self.backend.window_control()   # one per thread
        except Exception as e:  # noqa: BLE001
            log.error("window control: %s", e)
            return
        cfg, window = self._context(windows)
        if window is not None and is_launcher(cfg, window):
            return
        app = app_for_window(cfg, window) if window else None
        if app and app.get("pause_on_home"):
            try:
                paused = self.media.pause_all()
                log.info("guide in %s: paused %s", app.get("name", "?"), paused or "nothing (no player was playing)")
            except Exception as e:  # noqa: BLE001 - pausing is a nicety: still go home
                log.warning("could not pause: %s", e)
        try:
            self._show_launcher(cfg, windows)
        except Exception as e:
            log.error("guide failed: %s", e)

    def close(self):
        if not self.action.ready():
            return
        cfg, window = self._context()
        if window is None or is_launcher(cfg, window):
            return
        app = app_for_window(cfg, window)

        if app and app.get("close_on_second_press"):
            now = time.monotonic()
            if now - self.first_press > SECOND_PRESS_WINDOW:
                self.first_press = now
                log.info("%s: first press (the app itself ends the stream)", app.get("name", "?"))
                return
            self.first_press = 0.0

        # Closing can take a few seconds; do it in a thread so the guide
        # button keeps responding meanwhile.
        threading.Thread(target=self._close, args=(cfg, window, app), daemon=True).start()

    def _close(self, cfg, window, app):
        try:
            windows = self.backend.window_control()  # one per thread
            target = (app.get("id") if app else None) or window.app_id
            name = (app.get("name") if app else None) or target or window.title or "?"
            timeout = (app or {}).get("close_timeout", DEFAULT_CLOSE_TIMEOUT)

            command = (app or {}).get("close")
            if command:
                log.info("closing %s with %s", name, command)
                self.system.spawn(command)
            else:
                log.info("closing %s (%d window(s))", name, windows.close(target))

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.25)
                if not windows.is_running(target):
                    break
            else:
                self.system.force_close(target, window.pid)

            self._show_launcher(cfg, windows)
        except Exception as e:
            log.error("close failed: %s", e)


POINTER_EVERY = 3.0  # seconds: at most one "hide the pointer" request per this


class GamepadShortcuts:
    """Tracks held buttons per gamepad and fires the shortcuts. Using the gamepad
    also hides the mouse pointer (it comes back when the mouse moves)."""

    def __init__(self, shortcuts, settings=None, clock=time.monotonic):
        self.shortcuts = shortcuts
        self.settings = settings or config.load_quietly
        self.clock = clock
        self.held = {}  # device -> set of button names
        self.repeat = None  # (device, direction, combo, when) while a volume combo is held
        self.pointer = Throttle(POINTER_EVERY)

    def _hide_pointer(self):
        if self.pointer.ready():
            try:
                self.shortcuts.windows.hide_pointer()
            except Exception as e:  # noqa: BLE001 - never let this stop the shortcuts
                log.warning("could not hide the pointer: %s", e)

    def handle(self, event):
        if event.kind != "button":
            return
        held = self.held.setdefault(event.device, set())
        if event.value:
            self._hide_pointer()
            held.add(event.name)
            if len(held) < 2:
                return   # every combo has at least two buttons: no need to read the config
            for name, combo in VOLUME_COMBOS.items():
                if event.name in combo and combo <= held:
                    direction = 1 if name == "up" else -1
                    self.shortcuts.volume(direction)
                    self.repeat = (event.device, direction, combo, self.clock() + REPEAT_DELAY)
                    return
            try:
                current = combos(self.settings())
            except Exception as e:  # noqa: BLE001 - a broken apps.json: keep the defaults
                log.warning("could not read the shortcuts: %s", e)
                current = DEFAULT_COMBOS
            if event.name in current["home"] and current["home"] <= held:
                self.shortcuts.guide()
            elif event.name in current["close"] and current["close"] <= held:
                self.shortcuts.close()
        else:
            held.discard(event.name)
            if self.repeat and self.repeat[0] == event.device and event.name in self.repeat[2]:
                self.repeat = None

    def forget(self, device):
        self.held.pop(device, None)
        if self.repeat and self.repeat[0] == device:
            self.repeat = None

    def timeout(self, idle):
        """How long the caller may wait for events: short while a volume combo repeats."""
        if self.repeat is None:
            return idle
        return max(0.0, min(idle, self.repeat[3] - self.clock()))

    def tick(self):
        """Repeat the volume step while its combo is still held."""
        if self.repeat is None:
            return
        device, direction, combo, when = self.repeat
        if not combo <= self.held.get(device, set()):
            self.repeat = None
            return
        now = self.clock()
        if now >= when:
            self.shortcuts.volume(direction)
            nxt = when + REPEAT_EVERY
            self.repeat = (device, direction, combo, nxt if nxt > now else now + REPEAT_EVERY)
