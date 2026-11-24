# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Installed applications and their icons on Linux, from .desktop files (system, user and Flatpak)."""

import logging
import os
from pathlib import Path

from gi.repository import Gio

from ..base import AppCatalog, IconRef, InstalledApp

log = logging.getLogger("htpc")

GENERIC_ICON = "application-x-executable"
LAUNCHER_DESKTOP = "htpc-launcher.desktop"

# Where Flatpak publishes the .desktop files and icons of installed apps. They are
# usually on the session's XDG_DATA_DIRS already; looking here too covers when not.
FLATPAK_EXPORTS = [Path.home() / ".local/share/flatpak/exports/share",
                   Path("/var/lib/flatpak/exports/share")]


def _icon_ref(gicon):
    if gicon is None:
        return IconRef(names=(GENERIC_ICON,))
    if isinstance(gicon, Gio.FileIcon):
        return IconRef(path=gicon.get_file().get_path())
    if isinstance(gicon, Gio.ThemedIcon):
        return IconRef(names=tuple(gicon.get_names()) + (GENERIC_ICON,))
    return IconRef(names=(GENERIC_ICON,))


def _app_id(desktop_id):
    return desktop_id[:-len(".desktop")] if desktop_id.endswith(".desktop") else desktop_id


class DesktopCatalog(AppCatalog):
    def _info(self, desktop_id):
        try:
            info = Gio.DesktopAppInfo.new(desktop_id)
        except TypeError:
            info = None
        if info:
            return info
        for base in FLATPAK_EXPORTS:
            path = base / "applications" / desktop_id
            if path.exists():
                return Gio.DesktopAppInfo.new_from_filename(str(path))
        return None

    def _info_for(self, app):
        for desktop_id in (app.get("desktop"), f"{app['id']}.desktop" if app.get("id") else None):
            if desktop_id:
                info = self._info(desktop_id)
                if info:
                    return info
        return None

    def installed(self):
        seen = {}
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo) and info.should_show():
                seen[info.get_id()] = info
        # Flatpak apps, in case the session is not looking at their folder.
        for base in FLATPAK_EXPORTS:
            folder = base / "applications"
            if not folder.is_dir():
                continue
            for path in folder.glob("*.desktop"):
                if path.name in seen:
                    continue
                info = Gio.DesktopAppInfo.new_from_filename(str(path))
                if info and info.should_show():
                    seen[path.name] = info
        seen.pop(LAUNCHER_DESKTOP, None)
        apps = []
        for desktop_id, info in seen.items():
            wm_class = info.get_startup_wm_class()
            apps.append(InstalledApp(
                id=_app_id(desktop_id),
                name=info.get_display_name(),
                launch=["gio", "launch", info.get_filename()],
                icon=_icon_ref(info.get_icon()),
                desktop=desktop_id,
                extra_ids=[wm_class] if wm_class else [],
            ))
        return sorted(apps, key=lambda a: a.name.casefold())

    def describe(self, app):
        info = self._info_for(app)
        return info.get_display_name() if info else None

    def icon_for(self, app):
        icon = app.get("icon")
        if icon:
            icon = os.path.expanduser(icon)
            if not os.path.isabs(icon):
                return IconRef(names=(icon, GENERIC_ICON))
            if os.path.exists(icon):
                return IconRef(path=icon)
            log.warning("icon not found: %s - using the app's own", icon)
        info = self._info_for(app)
        if info and info.get_icon():
            return _icon_ref(info.get_icon())
        # Flatpak also publishes the icon under the app id itself.
        if app.get("id"):
            return IconRef(names=(app["id"], GENERIC_ICON))
        return IconRef(names=(GENERIC_ICON,))

    def icon_dirs(self):
        return [str(base / "icons") for base in FLATPAK_EXPORTS if (base / "icons").is_dir()]
