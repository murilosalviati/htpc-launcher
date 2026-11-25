# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Starting and stopping programs, restart and shut down on Linux.
Also which kind of connection is in use, asked to NetworkManager."""

import glob
import logging
import os
import re
import select
import shutil
import signal
import subprocess
import threading
import time

from ..base import System
from .dbus import DBusAddress, DBusClient

log = logging.getLogger("htpc")

FLATPAK_TIMEOUT = 5   # seconds for flatpak info / kill (it can block while an update runs)
KILL_AFTER = 2.0      # seconds between SIGTERM and SIGKILL, if the process is still alive


# What a program needs to reach the graphical session (X apps like Steam need
# DISPLAY and XAUTHORITY even on Wayland, through Xwayland).
SESSION_VARS = ("WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS",
                "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP")


def session_env():
    """The graphical session's variables as GNOME registered them in the user's
    systemd manager (`systemctl --user show-environment`). Empty if unavailable."""
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    env = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in SESSION_VARS:
            continue
        if value.startswith("$'") and value.endswith("'"):  # systemd's quoting for odd characters
            value = value[2:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        env[key] = value
    return env


def graphical_env():
    """Environment for the programs we start.

    The launcher or the controller may have been started from somewhere without
    the session's variables: the user's systemd services, or an SSH shell (which
    has no DISPLAY or XAUTHORITY, so Steam says "Check your DISPLAY"). Missing
    ones are taken from the session, then from the usual defaults.
    """
    env = dict(os.environ)
    for key, value in session_env().items():
        env.setdefault(key, value)
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("DISPLAY", ":0")
    if "XAUTHORITY" not in env:
        # GNOME's Xwayland keeps its key in a file like /run/user/1000/.mutter-Xwaylandauth.ABC123
        keys = sorted(glob.glob(f"{runtime}/.mutter-Xwaylandauth.*"), key=os.path.getmtime)
        if keys:
            env["XAUTHORITY"] = keys[-1]
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    env.setdefault("XDG_SESSION_TYPE", "wayland")
    return env


class LinuxSystem(System):
    def spawn(self, command):
        try:
            subprocess.Popen(command, start_new_session=True, env=graphical_env(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as e:
            log.error("could not start %s: %s", command, e)
            return False

    def force_close(self, app_id, pid):
        try:
            if app_id and subprocess.run(["flatpak", "info", app_id], capture_output=True,
                                         timeout=FLATPAK_TIMEOUT).returncode == 0:
                log.info("forcing: flatpak kill %s", app_id)
                subprocess.run(["flatpak", "kill", app_id], capture_output=True, timeout=FLATPAK_TIMEOUT)
                return
        except subprocess.TimeoutExpired:
            log.warning("flatpak did not answer (an update running?); trying the process itself")
        if not pid or pid <= 1 or pid == os.getpid():
            log.warning("don't know how to force %r to close", app_id)
            return
        # A pidfd pins the process: if it exits and its PID gets reused, signals
        # through the pidfd can't reach the new process.
        try:
            pidfd = os.pidfd_open(pid)
        except ProcessLookupError:
            return   # already gone
        except (OSError, AttributeError) as e:
            log.warning("can't watch pid %d safely (%s); sending SIGTERM only", pid, e)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return
        try:
            log.info("forcing: SIGTERM to pid %d", pid)
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            exited, _, _ = select.select([pidfd], [], [], KILL_AFTER)   # readable once it has exited
            if not exited:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                log.info("SIGKILL to pid %d", pid)
        except ProcessLookupError:
            pass
        finally:
            os.close(pidfd)

    # --- volume: PipeWire (wpctl), or PulseAudio (pactl) ------------------------------

    def _run(self, command):
        # C locale: the output is parsed ("45%", "Volume: 0.45"), so no translated words or decimal commas.
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run(command, capture_output=True, text=True, timeout=3, check=True, env=env).stdout

    def change_volume(self, step):
        if shutil.which("wpctl"):
            sink = "@DEFAULT_AUDIO_SINK@"
            if step > 0:
                self._run(["wpctl", "set-mute", sink, "0"])
            self._run(["wpctl", "set-volume", "-l", "1.0", sink, f"{abs(step):.2f}{'+' if step > 0 else '-'}"])
            out = self._run(["wpctl", "get-volume", sink])   # "Volume: 0.45" or "Volume: 0.45 [MUTED]"
            match = re.search(r"([0-9.]+)", out)
            return (min(1.0, float(match.group(1))) if match else 0.0), "MUTED" in out
        if shutil.which("pactl"):
            sink = "@DEFAULT_SINK@"
            if step > 0:
                self._run(["pactl", "set-sink-mute", sink, "0"])
                current = self._pactl_level(sink)
                points = min(100, round(current * 100 + step * 100))
                self._run(["pactl", "set-sink-volume", sink, f"{points}%"])
            else:
                self._run(["pactl", "set-sink-volume", sink, f"-{round(abs(step) * 100)}%"])
            muted = "yes" in self._run(["pactl", "get-sink-mute", sink])
            return self._pactl_level(sink), muted
        log.warning("no wpctl or pactl: can't change the volume")
        return None

    def _pactl_level(self, sink):
        out = self._run(["pactl", "get-sink-volume", sink])   # "... front-left: 29491 /  45% / ..."
        match = re.search(r"(\d+)%", out)
        return int(match.group(1)) / 100 if match else 0.0

    def reboot(self):
        self.spawn(["systemctl", "reboot"])

    def power_off(self):
        self.spawn(["systemctl", "poweroff"])

    # NetworkManager's PrimaryConnectionType: "802-11-wireless", "802-3-ethernet",
    # "bridge", "bond", "vpn", "gsm"... or "" when there is no connection.
    WIFI_TYPES = ("802-11-wireless", "802-11-olpc-mesh", "wifi-p2p")

    def connection_kind(self):
        kind = self._nm_property("PrimaryConnectionType")
        if not kind:
            return None
        return "wifi" if kind in self.WIFI_TYPES else "wired"

    # NetworkManager's Connectivity: 0 unknown, 1 none, 2 portal, 3 limited, 4 full.
    CONNECTIVITY = {1: "none", 2: "limited", 3: "limited", 4: "full"}

    def connectivity(self):
        return self.CONNECTIVITY.get(self._nm_property("Connectivity"))

    def _nm_property(self, name):
        watch = NetworkWatch.shared()
        if watch.live:
            return watch.values.get(name)
        try:   # the watch is not running (yet): ask
            return _nm_client().get(NM, name, timeout=1)
        except Exception as e:  # noqa: BLE001 - no NetworkManager, no system bus...
            log.debug("NetworkManager not reachable: %s", e)
            return None


# --- NetworkManager ----------------------------------------------------------------------

NM = DBusAddress("/org/freedesktop/NetworkManager", bus_name="org.freedesktop.NetworkManager",
                 interface="org.freedesktop.NetworkManager")
_nm = None


def _nm_client():
    global _nm
    if _nm is None:
        _nm = DBusClient("SYSTEM")
    return _nm


class NetworkWatch:
    """NetworkManager's connectivity and connection type, kept up to date by its
    PropertiesChanged signal, in a thread of its own: one per process, started on
    first use. Asking only when something changed, instead of every few seconds.
    While it is not running (no NetworkManager yet, a lost bus), `live` is False
    and LinuxSystem asks directly; it tries again every RETRY seconds."""

    PROPERTIES = ("Connectivity", "PrimaryConnectionType")
    RETRY = 30.0
    _shared = None
    _shared_lock = threading.Lock()

    @classmethod
    def shared(cls):
        with cls._shared_lock:
            if cls._shared is None:
                cls._shared = cls()
                threading.Thread(target=cls._shared.run, daemon=True, name="network-watch").start()
            return cls._shared

    def __init__(self):
        self.values = {}
        self.live = False

    def run(self):
        while True:
            try:
                self._watch()
            except Exception as e:  # noqa: BLE001 - no NetworkManager, bus gone...
                log.debug("network watch: %s", e)
            self.live = False
            time.sleep(self.RETRY)

    def _watch(self):
        from jeepney import MatchRule, Properties
        from jeepney.bus_messages import message_bus
        from jeepney.io.blocking import open_dbus_connection
        from jeepney.wrappers import unwrap_msg
        rule = MatchRule(type="signal", sender=NM.bus_name, path=NM.object_path,
                         interface="org.freedesktop.DBus.Properties", member="PropertiesChanged")
        rule.add_arg_condition(0, NM.interface)
        with open_dbus_connection(bus="SYSTEM") as conn:
            unwrap_msg(conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=2))
            # Listening first, then reading: a change in between is not lost.
            with conn.filter(rule, bufsize=32) as queue:
                for name in self.PROPERTIES:
                    self.values[name] = unwrap_msg(
                        conn.send_and_get_reply(Properties(NM).get(name), timeout=2))[0][1]
                self.live = True
                while True:
                    _interface, changed, _invalidated = conn.recv_until_filtered(queue).body
                    for name in self.PROPERTIES:
                        if name in changed:
                            self.values[name] = changed[name][1]
