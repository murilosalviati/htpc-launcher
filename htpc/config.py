# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""apps.json handling, shared by the launcher and the controller service.

The file lives in paths.config_file() (~/.config/htpc-launcher/apps.json on
Linux). Older installs used
Portuguese keys ("nome", "abrir", ...); load() translates them to the
current English keys, so an old file keeps working without manual edits.
A migrated file defaults to the Portuguese UI ("language": "pt-BR"),
since that is what its owner was already seeing.
"""

import json
import os
from pathlib import Path

from . import paths

DEFAULT_LANGUAGE = "en"

# Old (Portuguese) key -> current key, per app entry.
LEGACY_APP_KEYS = {
    "nome": "name",
    "icone": "icon",
    "abrir": "launch",
    "outros_ids": "extra_ids",
    "fechar": "close",
    "espera_fechar": "close_timeout",
    "pausar_ao_sair": "pause_on_home",
    "fechar_em_dois_toques": "close_on_second_press",
    "janelas_preferidas": "preferred_windows",
}
LEGACY_LAUNCHER_KEYS = {"abrir": "launch"}

# Settings added after the Portuguese-key versions, filled in for known apps
# when an old file is converted (only if the entry does not have them yet).
NEW_DEFAULTS = {
    "com.valvesoftware.Steam": {
        "on_resume": ["flatpak", "run", "com.valvesoftware.Steam", "steam://open/bigpicture"],
    },
}

# Defaults for known apps, filled in on every load when the entry does not set
# them. Steam's Big Picture is already full screen and Steam's other windows
# (Friends List, Special Offers...) should not be.
KNOWN_APP_DEFAULTS = {
    "com.valvesoftware.Steam": {"fullscreen": False},
}

# The folder of user-chosen icons was renamed too.
LEGACY_ICON_DIR = "/htpc-launcher/icones-apps/"
ICON_DIR = "/htpc-launcher/app-icons/"


def _rename_keys(entry, mapping):
    changed = False
    for old, new in mapping.items():
        if old in entry:
            value = entry.pop(old)
            entry.setdefault(new, value)
            changed = True
    return changed


def migrate(cfg):
    """Bring a config dict to the current format, in place. Returns True if it changed."""
    changed = _rename_keys(cfg.setdefault("launcher", {}), LEGACY_LAUNCHER_KEYS)
    for app in cfg.setdefault("apps", []):
        changed |= _rename_keys(app, LEGACY_APP_KEYS)
        icon = app.get("icon")
        if icon and LEGACY_ICON_DIR in icon:
            app["icon"] = icon.replace(LEGACY_ICON_DIR, ICON_DIR)
            changed = True
    if changed:
        for app in cfg["apps"]:
            for key, value in NEW_DEFAULTS.get(app.get("id"), {}).items():
                app.setdefault(key, value)
        cfg.setdefault("language", "pt-BR")
    return changed


def load(path=None):
    """Read apps.json. Returns (config, migrated)."""
    path = Path(path or paths.config_file())
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    migrated = migrate(cfg)
    cfg.setdefault("language", DEFAULT_LANGUAGE)
    for app in cfg.get("apps", []):
        for key, value in KNOWN_APP_DEFAULTS.get(app.get("id"), {}).items():
            app.setdefault(key, value)
    return cfg, migrated


def save(cfg, path=None):
    """Write apps.json atomically (temporary file + rename)."""
    path = Path(path or paths.config_file())
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def exists():
    return paths.config_file().exists()
