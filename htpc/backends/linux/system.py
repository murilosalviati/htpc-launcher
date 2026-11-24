# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Starting and stopping programs, restart and shut down on Linux."""

import logging
import os
import signal
import subprocess
import time

from ..base import System

log = logging.getLogger("htpc")


def graphical_env():
    """Environment for the programs we start.

    The controller runs under the user's systemd, which does not always receive
    the graphical session's variables. Only missing ones are filled in.
    """
    env = dict(os.environ)
    runtime = env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("DISPLAY", ":0")
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

    def reboot(self):
        self.spawn(["systemctl", "reboot"])

    def power_off(self):
        self.spawn(["systemctl", "poweroff"])
