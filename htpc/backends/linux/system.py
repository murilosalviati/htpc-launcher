# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Starting and stopping programs, restart and shut down on Linux.
Also which kind of connection is in use, asked to NetworkManager."""

import glob
import logging
import os
import re
import shutil
import signal
import subprocess
import time

from ..base import System

log = logging.getLogger("htpc")


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
        if app_id and subprocess.run(["flatpak", "info", app_id], capture_output=True).returncode == 0:
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

    # --- volume: PipeWire (wpctl), or PulseAudio (pactl) ------------------------------

    def _run(self, command):
        return subprocess.run(command, capture_output=True, text=True, timeout=3, check=True).stdout

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

    def _nm_primary_type(self):
        return self._nm_property("PrimaryConnectionType")

    def _nm_property(self, name):
        try:
            from jeepney import DBusAddress, Properties
            from jeepney.io.blocking import open_dbus_connection
            from jeepney.wrappers import unwrap_msg
            if getattr(self, "_nm", None) is None:
                self._nm = open_dbus_connection(bus="SYSTEM")
            addr = DBusAddress("/org/freedesktop/NetworkManager",
                               bus_name="org.freedesktop.NetworkManager",
                               interface="org.freedesktop.NetworkManager")
            reply = self._nm.send_and_get_reply(Properties(addr).get(name), timeout=1)
            return unwrap_msg(reply)[0][1]
        except Exception as e:  # no NetworkManager, no system bus...
            if getattr(self, "_nm", None) is not None:
                try:
                    self._nm.close()
                except Exception:
                    pass
            self._nm = None
            log.debug("NetworkManager not reachable: %s", e)
            return None
