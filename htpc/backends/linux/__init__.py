# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Linux backend: GNOME on Wayland.

  windows   window control through the htpc-launcher@htpc GNOME Shell extension (D-Bus)
  media     MPRIS over D-Bus
  gamepads  evdev
  apps      .desktop files (system, user, Flatpak) through Gio
  system    systemd for restart/shut down, Flatpak and signals to force-close

Needs python3-jeepney and python3-evdev; the app catalog also needs python3-gi.
"""

from ..base import Backend


class LinuxBackend(Backend):
    name = "linux"

    def window_control(self):
        from .windows import ExtensionWindowControl
        return ExtensionWindowControl()

    def media(self):
        from .media import MprisMedia
        return MprisMedia()

    def gamepads(self):
        from .gamepads import EvdevGamepads
        return EvdevGamepads()

    def apps(self):
        from .apps import DesktopCatalog
        return DesktopCatalog()

    def system(self):
        from .system import LinuxSystem
        return LinuxSystem()
