# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Where HTPC Launcher keeps its files on each operating system.

Linux:   ~/.config/htpc-launcher        (or $XDG_CONFIG_HOME/htpc-launcher)
         ~/.local/share/htpc-launcher   (or $XDG_DATA_HOME/htpc-launcher)
Windows: %APPDATA%\\htpc-launcher        (configuration)
         %LOCALAPPDATA%\\htpc-launcher   (program files and icons)
"""

import os
import sys
from pathlib import Path

APP = "htpc-launcher"


def _windows():
    return sys.platform.startswith("win")


def config_dir():
    if _windows():
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP


def data_dir():
    if _windows():
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP


def config_file():
    return config_dir() / "apps.json"


def app_icons_dir():
    """Icons chosen by the user, offered in the app editor."""
    return data_dir() / "app-icons"
