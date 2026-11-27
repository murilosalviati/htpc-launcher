# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Window control on GNOME/Wayland, through the htpc-launcher@htpc GNOME Shell extension.

On Wayland a regular program cannot raise other apps' windows or see which
window has focus; the extension runs inside GNOME Shell and offers that on the
session bus (org.htpc.Launcher at /org/htpc/Launcher).
"""

import json
import logging

from ..base import Window, WindowControl
from .dbus import DBusAddress, DBusClient, DBusErrorResponse

log = logging.getLogger("htpc")

LAUNCHER_ID = "htpc-launcher"
EXTENSION = DBusAddress("/org/htpc/Launcher", bus_name="org.htpc.Launcher", interface="org.htpc.Launcher")


class ExtensionWindowControl(WindowControl):
    def __init__(self):
        self.dbus = DBusClient("SESSION")

    def _call(self, method, signature=None, args=()):
        """The method's first return value, or None if the extension could not be reached."""
        try:
            return self.dbus.call(EXTENSION, method, signature, args)[0]
        except DBusErrorResponse as e:
            log.warning("GNOME extension refused %s: %s", method, e)
        except Exception as e:  # noqa: BLE001 - bus gone, timeout...
            log.warning("GNOME extension did not answer %s: %s", method, e)
        return None

    def windows(self):
        data = self._call("ListWindows")
        if data is None:
            return None
        return [Window(app_id=w.get("appId", ""), ids=w.get("ids", []), title=w.get("title", ""),
                       pid=w.get("pid", 0), focused=w.get("focused", False))
                for w in json.loads(data)]

    def is_running(self, app_id):
        return bool(self._call("IsRunning", "s", (app_id,)))

    def activate(self, app_id, preferred_titles=()):
        if preferred_titles:
            r = self._call("ActivatePreferring", "sas", (app_id, list(preferred_titles)))
            if r is not None:
                return bool(r)
            # an older extension without that method: bring any window of the app
        r = self._call("Activate", "s", (app_id,))
        return None if r is None else bool(r)

    def close(self, app_id):
        return self._call("Close", "s", (app_id,)) or 0

    def show_launcher(self):
        return bool(self._call("ShowLauncher"))

    def notify(self, title, body, icon_path, seconds=6):
        # Extension v5 and later.
        return self._call("Notify", "sssu", (title, body, icon_path, int(seconds)))

    def show_osd(self, icon_name, level):
        # Extension v6 and later.
        return self._call("ShowOsd", "sd", (icon_name, float(level)))

    def show_shortcuts(self, title, rows):
        # Extension v8 and later: rows [(buttons, what they do), ...].
        return self._call("ShowShortcuts", "ss", (title, json.dumps([list(r) for r in rows])))

    def hide_shortcuts(self):
        # Extension v8 and later.
        return self._call("HideShortcuts")

    def hide_pointer(self):
        # Extension v4 and later.
        return self._call("HidePointer")

    def fullscreen_on_open(self, app_id, seconds=60):
        # Extension v3 and later; an older one answers None (logged once per call).
        return self._call("FullscreenOnOpen", "su", (app_id, int(seconds)))
