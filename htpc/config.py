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
import logging
import os
import time
from pathlib import Path

from . import paths

log = logging.getLogger("htpc")

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


def backup_path(path=None):
    """apps.json.bak: a copy of the last apps.json that was written successfully."""
    return Path(path or paths.config_file()).with_suffix(".json.bak")


def _read(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("apps", []), list):
        raise ValueError(f"{path} is not an HTPC Launcher configuration")
    return cfg


def load(path=None, fallback=False):
    """Read apps.json. Returns (config, migrated).
    With fallback, a broken or missing apps.json is replaced by the last good copy
    (apps.json.bak); the broken file is kept as apps.json.broken. Without a good
    copy the original error is raised."""
    path = Path(path or paths.config_file())
    try:
        cfg = _read(path)
    except (OSError, ValueError) as e:
        backup = backup_path(path)
        if not fallback or not backup.exists():
            raise
        cfg = _read(backup)
        log.error("apps.json could not be read (%s); using the last good copy, %s", e, backup)
        if path.exists():
            os.replace(path, path.with_suffix(".json.broken"))
        _write(path, cfg)
    else:
        if not backup_path(path).exists():
            _write(backup_path(path), cfg)
        _private(path)
    migrated = migrate(cfg)
    cfg.setdefault("language", DEFAULT_LANGUAGE)
    for app in cfg.get("apps", []):
        for key, value in KNOWN_APP_DEFAULTS.get(app.get("id"), {}).items():
            app.setdefault(key, value)
    return cfg, migrated


_quiet_cache = {}   # path -> ((inode, size, mtime), config) for load_quietly
SETTLED = 2.0       # seconds: a file changed more recently than this is read again


def load_quietly(path=None):
    """For the background service: apps.json, else the last good copy, else {}.
    Never raises and never writes (the launcher is the one that repairs the file).

    The service asks for it on every combo press and every few seconds, so an
    unchanged file is not read again: the answer is shared, and callers must not
    change it. A file is only remembered once it has not changed for SETTLED
    seconds, so a second write within the file system's timestamp step (same
    size, same mtime) can't leave an old copy in use."""
    path = Path(path or paths.config_file())
    try:
        st = os.stat(path)
        key = (st.st_ino, st.st_size, st.st_mtime_ns)
    except OSError:
        key = None
    cached = _quiet_cache.get(path)
    if key is not None and cached is not None and cached[0] == key:
        return cached[1]
    for candidate in (path, backup_path(path)):
        try:
            cfg = _read(candidate)
        except (OSError, ValueError):
            continue
        migrate(cfg)
        if candidate == path and key is not None and time.time() - st.st_mtime >= SETTLED:
            _quiet_cache[path] = (key, cfg)
        else:
            _quiet_cache.pop(path, None)
        return cfg
    _quiet_cache.pop(path, None)
    return {}


def _private(path):
    """Only the owner may read apps.json: it can hold a Home Assistant token."""
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


def _write(path, cfg):
    """Write atomically (temporary file + rename), readable only by the owner."""
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def save(cfg, path=None):
    """Write apps.json, and keep the same content as the last good copy (apps.json.bak)."""
    path = Path(path or paths.config_file())
    _write(path, cfg)
    _write(backup_path(path), cfg)


def exists():
    return paths.config_file().exists()
