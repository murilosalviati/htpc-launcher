#!/usr/bin/env python3
"""HTPC controller service.

Reads every connected gamepad (Xbox, 8BitDo, PS4...) without taking the
buttons away from the apps, and handles two shortcuts:

  * Guide (Xbox / Home / PS): pauses the video if the focused app is a video
    app, then shows the launcher. The app keeps running behind it.
  * Start + Select + L1 + R1: closes the focused app and goes back to the
    launcher. For apps with "close_on_second_press" (Moonlight), the first
    press belongs to the app (it ends the stream) and a second press within
    15 s closes it.

Depends on the "HTPC Launcher Bridge" GNOME extension (D-Bus org.htpc.Launcher)
and on ~/.config/htpc-launcher/apps.json.

Packages: sudo apt install python3-evdev python3-jeepney
"""

import json
import logging
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import evdev
from evdev import ecodes
from jeepney import DBusAddress, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

# htpc_config.py is installed next to this file (it comes from common/ in the repo).
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent / "common"))
import htpc_config  # noqa: E402

CLOSE_COMBO = {ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL, ecodes.BTN_TR}
GUIDE_BUTTON = ecodes.BTN_MODE

# Steam creates a virtual gamepad that repeats the real gamepad's events;
# an action inside this interval is treated as a repeat and ignored.
MIN_INTERVAL = 1.0
SECOND_PRESS_WINDOW = 15.0    # close_on_second_press: time allowed for the 2nd press
DEFAULT_CLOSE_TIMEOUT = 3.0   # how long to wait for an app to close before forcing it
RESCAN_INTERVAL = 2.0         # how often to look for new gamepads

log = logging.getLogger("htpc-controller")


# ---------------------------------------------------------------------------
# Configuration

def load_config():
    return htpc_config.load()[0]


def app_ids(app):
    return [i.lower() for i in [app["id"], *app.get("extra_ids", [])] if i]


def app_for_window(cfg, window):
    """Find the apps.json entry that owns a window (by the names the extension reports)."""
    names = set(window.get("ids", [])) | {window.get("appId", "").lower()}
    for app in cfg.get("apps", []):
        if names & set(app_ids(app)):
            return app
    return None


def is_launcher(cfg, window):
    lid = cfg.get("launcher", {}).get("id", "htpc-launcher").lower()
    return lid in window.get("ids", []) or window.get("appId", "").lower() == lid


# ---------------------------------------------------------------------------
# D-Bus: the GNOME extension and media players (MPRIS)

class Shell:
    """Talks to the HTPC Launcher Bridge extension. One per thread."""

    def __init__(self):
        self.conn = open_dbus_connection(bus="SESSION")
        self.addr = DBusAddress("/org/htpc/Launcher", bus_name="org.htpc.Launcher",
                                interface="org.htpc.Launcher")

    def _call(self, method, signature=None, args=()):
        msg = new_method_call(self.addr, method, signature, args)
        return unwrap_msg(self.conn.send_and_get_reply(msg, timeout=2))

    def windows(self):
        return json.loads(self._call("ListWindows")[0])

    def focused_window(self):
        return next((w for w in self.windows() if w.get("focused")), None)

    def show_launcher(self):
        return self._call("ShowLauncher")[0]

    def close(self, app_id):
        return self._call("Close", "s", (app_id,))[0]

    def is_running(self, app_id):
        return self._call("IsRunning", "s", (app_id,))[0]

    def pause_media(self):
        """Pause every MPRIS player that is playing. Returns the names it paused."""
        names = unwrap_msg(self.conn.send_and_get_reply(message_bus.ListNames(), timeout=2))[0]
        paused = []
        for name in names:
            if not name.startswith("org.mpris.MediaPlayer2."):
                continue
            player = DBusAddress("/org/mpris/MediaPlayer2", bus_name=name,
                                 interface="org.mpris.MediaPlayer2.Player")
            try:
                status = unwrap_msg(self.conn.send_and_get_reply(
                    Properties(player).get("PlaybackStatus"), timeout=1))[0][1]
                if status == "Playing":
                    unwrap_msg(self.conn.send_and_get_reply(
                        new_method_call(player, "Pause"), timeout=1))
                    paused.append(name)
            except Exception as e:  # one broken player must not block the rest
                log.debug("could not pause %s: %s", name, e)
        return paused


# ---------------------------------------------------------------------------
# Actions

def graphical_env():
    """Environment for the programs this service starts (launcher, Steam -shutdown).

    The service runs under the user's systemd, which does not always receive
    the graphical session's variables. Only missing ones are filled in.
    """
    env = dict(os.environ)
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("DISPLAY", ":0")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    return env


def spawn(command):
    return subprocess.Popen(command, start_new_session=True, env=graphical_env(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def force_close(app_id, pid):
    """Last resort when an app does not close on its own."""
    if app_id and subprocess.run(["flatpak", "info", app_id],
                                 capture_output=True).returncode == 0:
        log.info("forcing: flatpak kill %s", app_id)
        subprocess.run(["flatpak", "kill", app_id], capture_output=True)
        return
    if not pid or pid <= 1 or pid == os.getpid():
        log.warning("don't know how to force %r to close", app_id)
        return
    log.info("forcing: SIGTERM to pid %d", pid)
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        os.kill(pid, signal.SIGKILL)
        log.info("SIGKILL to pid %d", pid)
    except ProcessLookupError:
        pass


class Actions:
    def __init__(self, shell_factory=Shell):
        self.shell_factory = shell_factory
        self._shell = None
        self.last_action = 0.0
        self.first_press = 0.0

    @property
    def shell(self):
        if self._shell is None:
            self._shell = self.shell_factory()
        return self._shell

    def _ready(self):
        now = time.monotonic()
        if now - self.last_action < MIN_INTERVAL:
            return False
        self.last_action = now
        return True

    def _context(self):
        """(config, focused window); the window is None if the extension did not answer."""
        cfg = load_config()
        try:
            window = self.shell.focused_window()
        except Exception as e:
            log.error("GNOME extension did not answer: %s", e)
            self._shell = None  # reconnect next time
            return cfg, None
        return cfg, window

    def _show_launcher(self, cfg, shell):
        if shell.show_launcher():
            return
        command = cfg.get("launcher", {}).get("launch")
        if command:
            log.info("launcher was not running; starting it")
            spawn(command)
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
                paused = self.shell.pause_media()
                log.info("guide in %s: paused %s", app["name"], paused or "nothing (no player was playing)")
            self._show_launcher(cfg, self.shell)
        except Exception as e:
            log.error("guide failed: %s", e)
            self._shell = None

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
            shell = self.shell_factory()
            target = app["id"] if app else window.get("appId", "")
            name = app["name"] if app else (target or window.get("title", "?"))
            timeout = (app or {}).get("close_timeout", DEFAULT_CLOSE_TIMEOUT)

            command = (app or {}).get("close")
            if command:
                log.info("closing %s with %s", name, command)
                spawn(command)
            else:
                log.info("closing %s (%d window(s))", name, shell.close(target))

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                time.sleep(0.25)
                if not shell.is_running(target):
                    break
            else:
                force_close(target, window.get("pid"))

            self._show_launcher(cfg, shell)
        except Exception as e:
            log.error("close failed: %s", e)


# ---------------------------------------------------------------------------
# Reading the gamepads

def is_gamepad(dev):
    keys = dev.capabilities().get(ecodes.EV_KEY, [])
    return ecodes.BTN_SOUTH in keys and ecodes.BTN_START in keys


class Gamepads:
    def __init__(self, actions):
        self.actions = actions
        self.devs = {}       # path -> InputDevice
        self.pressed = {}    # path -> buttons currently held
        self.ignored = set()

    def rescan(self):
        paths = set(evdev.list_devices())
        self.ignored &= paths  # a device that disappeared may come back as something else
        for path in paths - self.devs.keys() - self.ignored:
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                self.ignored.add(path)  # no permission: keyboards, mice...
                continue
            if is_gamepad(dev):
                self.devs[path] = dev
                self.pressed[path] = set()
                log.info("gamepad connected: %s (%s)", dev.name, path)
            else:
                dev.close()
                self.ignored.add(path)

    def remove(self, path):
        dev = self.devs.pop(path, None)
        self.pressed.pop(path, None)
        if dev:
            log.info("gamepad disconnected: %s", dev.name)
            try:
                dev.close()
            except OSError:
                pass

    def handle(self, path, event):
        if event.type != ecodes.EV_KEY:
            return
        pressed = self.pressed[path]
        if event.value == 1:
            pressed.add(event.code)
            if event.code == GUIDE_BUTTON:
                self.actions.guide()
            elif event.code in CLOSE_COMBO and CLOSE_COMBO <= pressed:
                self.actions.close()
        elif event.value == 0:
            pressed.discard(event.code)

    def run(self):
        next_scan = 0.0
        while True:
            if time.monotonic() >= next_scan:
                self.rescan()
                next_scan = time.monotonic() + RESCAN_INTERVAL
            by_fd = {dev.fd: path for path, dev in self.devs.items()}
            ready, _, _ = select.select(list(by_fd), [], [], RESCAN_INTERVAL)
            for fd in ready:
                path = by_fd[fd]
                try:
                    for event in self.devs[path].read():
                        self.handle(path, event)
                except OSError:
                    self.remove(path)


def main():
    logging.basicConfig(level=os.environ.get("HTPC_LOG", "INFO"),
                        format="%(levelname)s %(message)s")
    if not htpc_config.CONFIG_PATH.exists():
        raise SystemExit(f"Missing configuration file: {htpc_config.CONFIG_PATH}")
    Gamepads(Actions()).run()


if __name__ == "__main__":
    main()
