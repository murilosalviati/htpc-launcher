# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""What the gamepad shortcuts do, independent of the operating system.

  * Guide: pauses media if the focused app has "pause_on_home", then shows the
    launcher. The app keeps running behind it.
  * Close combo (Start + Select + L1 + R1): closes the focused app and returns
    to the launcher. Apps with "close_on_second_press" (Moonlight) get the first
    press themselves (it ends the stream); a second press within 15 s closes them.

The controller service feeds normalized gamepad events into GamepadShortcuts;
Shortcuts does the work through the backend.
"""

import logging
import threading
import time

from . import config

CLOSE_COMBO = frozenset({"start", "select", "l1", "r1"})
GUIDE = "guide"

# Steam creates a virtual gamepad that repeats the real gamepad's events;
# an action inside this interval is treated as a repeat and ignored.
MIN_INTERVAL = 1.0
SECOND_PRESS_WINDOW = 15.0    # close_on_second_press: time allowed for the 2nd press
DEFAULT_CLOSE_TIMEOUT = 3.0   # how long to wait for an app to close before forcing it

log = logging.getLogger("htpc-controller")


def app_ids(app):
    return [i.lower() for i in [app["id"], *app.get("extra_ids", [])] if i]


def app_for_window(cfg, window):
    """The apps.json entry that owns a window (by the names the backend reports)."""
    names = set(window.ids) | {window.app_id.lower()}
    for app in cfg.get("apps", []):
        if names & set(app_ids(app)):
            return app
    return None


def is_launcher(cfg, window):
    lid = cfg.get("launcher", {}).get("id", "htpc-launcher").lower()
    return lid in window.ids or window.app_id.lower() == lid


class Shortcuts:
    def __init__(self, backend):
        self.backend = backend
        self.system = backend.system()
        self.media = backend.media()
        self._windows = None
        self.last_action = 0.0
        self.first_press = 0.0

    @property
    def windows(self):
        if self._windows is None:
            self._windows = self.backend.window_control()
        return self._windows

    def _ready(self):
        now = time.monotonic()
        if now - self.last_action < MIN_INTERVAL:
            return False
        self.last_action = now
        return True

    def _context(self):
        """(config, focused window); the window is None if the OS side did not answer."""
        cfg = config.load()[0]
        try:
            window = self.windows.focused()
        except Exception as e:
            log.error("window control did not answer: %s", e)
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

    def guide(self):
        if not self._ready():
            return
        cfg, window = self._context()
        if window is not None and is_launcher(cfg, window):
            return
        app = app_for_window(cfg, window) if window else None
        try:
            if app and app.get("pause_on_home"):
                paused = self.media.pause_all()
                log.info("guide in %s: paused %s", app["name"], paused or "nothing (no player was playing)")
            self._show_launcher(cfg, self.windows)
        except Exception as e:
            log.error("guide failed: %s", e)
            self._windows = None

    def close(self):
        if not self._ready():
            return
        cfg, window = self._context()
        if window is None or is_launcher(cfg, window):
            return
        app = app_for_window(cfg, window)

        if app and app.get("close_on_second_press"):
            now = time.monotonic()
            if now - self.first_press > SECOND_PRESS_WINDOW:
                self.first_press = now
                log.info("%s: first press (the app itself ends the stream)", app["name"])
                return
            self.first_press = 0.0

        # Closing can take a few seconds; do it in a thread so the guide
        # button keeps responding meanwhile.
        threading.Thread(target=self._close, args=(cfg, window, app), daemon=True).start()

    def _close(self, cfg, window, app):
        try:
            windows = self.backend.window_control()  # one per thread
            target = app["id"] if app else window.app_id
            name = app["name"] if app else (target or window.title or "?")
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

    def __init__(self, shortcuts):
        self.shortcuts = shortcuts
        self.held = {}  # device -> set of button names
        self.pointer_hidden_at = -POINTER_EVERY

    def _hide_pointer(self):
        now = time.monotonic()
        if now - self.pointer_hidden_at >= POINTER_EVERY:
            self.pointer_hidden_at = now
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
            if event.name == GUIDE:
                self.shortcuts.guide()
            elif event.name in CLOSE_COMBO and CLOSE_COMBO <= held:
                self.shortcuts.close()
        else:
            held.discard(event.name)

    def forget(self, device):
        self.held.pop(device, None)
