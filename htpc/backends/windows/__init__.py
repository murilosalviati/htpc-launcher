# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Windows backend: not written yet.

This is the plan for each piece, so the port can be done one class at a time
(see htpc/backends/base.py for the exact methods):

  windows   Win32 API (pywin32 or ctypes): EnumWindows + GetWindowThreadProcessId
            to list windows and map them to executables / AppUserModelIDs;
            SetForegroundWindow to raise (Windows limits focus stealing, so this
            needs the usual workarounds: AttachThreadInput or a synthetic Alt
            press); WM_CLOSE to close. No extension needed, unlike GNOME.
  media     Windows.Media.Control (GlobalSystemMediaTransportControlsSessionManager)
            through the winrt Python packages: pause every playing session.
  gamepads  SDL2 (pysdl2): reads Xbox, PlayStation and 8BitDo pads, including the
            guide button over HIDAPI. The Xbox button is also taken by the Xbox
            Game Bar and Steam, so the install notes must say how to turn those off.
  apps      Start Menu shortcuts (.lnk) and Store apps (shell:AppsFolder);
            icons extracted from the executables.
  system    subprocess for starting apps, TerminateProcess to force-close,
            "shutdown /r /t 0" and "shutdown /s /t 0".

The launcher UI is GTK 4; it runs on Windows (MSYS2 / gvsbuild) but is awkward
to package, so moving the UI to Qt is worth considering together with this port.
"""

from ..base import Backend


class WindowsBackend(Backend):
    name = "windows"

    def _todo(self, what):
        raise NotImplementedError(f"The Windows backend does not have {what} yet "
                                  "(see htpc/backends/windows/__init__.py).")

    def window_control(self):
        self._todo("window control")

    def media(self):
        self._todo("media control")

    def gamepads(self):
        self._todo("gamepad input")

    def apps(self):
        self._todo("the installed-apps list")

    def system(self):
        self._todo("process and power control")
