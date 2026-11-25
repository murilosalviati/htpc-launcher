# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The Steam games played most recently, for the home screen's "Games" tab.

Read from Steam's own files, without its API or an account key:

  * userdata/<user>/config/localconfig.vdf: when each game was last played
    ("LastPlayed") and for how long ("Playtime", minutes);
  * steamapps/appmanifest_<id>.acf, in every library folder: which games are
    installed, and their names;
  * appcache/librarycache: the cover art Steam already downloaded.

Works with the Flatpak Steam (~/.var/app/com.valvesoftware.Steam) and a
native one. Only installed games are listed (an uninstalled one can't start
from here), and Proton, the Steam runtimes and redistributables are left out.
"""

import re
from pathlib import Path

ROOTS = (
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ".var/app/com.valvesoftware.Steam/data/Steam",
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
)
NOT_GAMES = re.compile(r"^(proton\b|steam linux runtime|steamworks common|steamvr$)", re.IGNORECASE)
TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')
RECENT_LIMIT = 15


# --- Valve's KeyValues text format -----------------------------------------------------

def parse_vdf(text):
    """'"key" "value"' pairs and '"key" { ... }' blocks into nested dicts."""
    stack = [{}]
    key = None
    for m in TOKEN.finditer(re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)):
        string, brace = m.groups()
        if brace == "{":
            block = {}
            stack[-1][key if key is not None else ""] = block
            stack.append(block)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = string.replace('\\"', '"').replace("\\\\", "\\")
        else:
            stack[-1][key] = string.replace('\\"', '"').replace("\\\\", "\\")
            key = None
    return stack[0]


def _get(d, *path):
    """Nested lookup, ignoring case (Steam writes both "apps" and "Apps")."""
    for name in path:
        if not isinstance(d, dict):
            return None
        d = next((v for k, v in d.items() if k.lower() == name.lower()), None)
    return d


def _read(path):
    try:
        return parse_vdf(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


# --- finding things --------------------------------------------------------------------

def find_root(home=None):
    home = Path(home or Path.home())
    for rel in ROOTS:
        root = home / rel
        if (root / "steamapps").is_dir():
            return root.resolve()
    return None


def library_folders(root):
    folders = [root]
    data = _read(root / "steamapps" / "libraryfolders.vdf")
    for entry in (_get(data, "libraryfolders") or {}).values():
        path = _get(entry, "path") if isinstance(entry, dict) else None
        if path and Path(path).is_dir() and Path(path).resolve() not in folders:
            folders.append(Path(path).resolve())
    return folders


def installed(root):
    """{appid: name} of the installed games."""
    games = {}
    for folder in library_folders(root):
        for manifest in (folder / "steamapps").glob("appmanifest_*.acf"):
            state = _get(_read(manifest), "AppState") or {}
            appid, name = _get(state, "appid"), _get(state, "name")
            if appid and name and not NOT_GAMES.match(name):
                games[str(appid)] = name
    return games


def played(root):
    """{appid: (last played, minutes played)}, the latest of every Steam user here."""
    found = {}
    for config in (root / "userdata").glob("*/config/localconfig.vdf"):
        apps = _get(_read(config), "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {}
        for appid, info in apps.items():
            if not isinstance(info, dict):
                continue
            try:
                last = int(_get(info, "LastPlayed") or 0)
                minutes = int(_get(info, "Playtime") or 0)
            except ValueError:
                continue
            if last and last > found.get(appid, (0, 0))[0]:
                found[appid] = (last, minutes)
    return found


def art(root, appid, *names):
    """The first of these pictures Steam has cached for a game (its cache moved
    from appid_name.jpg to appid/name.jpg, then to appid/<hash>/name.jpg)."""
    cache = root / "appcache" / "librarycache"
    for name in names:
        for candidate in (cache / f"{appid}_{name}", cache / appid / name):
            if candidate.is_file():
                return str(candidate)
        found = sorted((cache / appid).glob(f"*/{name}")) if (cache / appid).is_dir() else []
        if found:
            return str(found[0])
    return None


def recent_games(home=None, limit=RECENT_LIMIT):
    """The installed games, most recently played first (never played: left out)."""
    root = find_root(home)
    if root is None:
        return []
    names, times = installed(root), played(root)
    order = sorted((a for a in names if a in times), key=lambda a: times[a][0], reverse=True)[:limit]
    return [{
        "id": f"steam:{appid}",
        "kind": "game",
        "appid": appid,
        "title": names[appid],
        "last_played": times[appid][0],
        "minutes": times[appid][1],
        "poster": art(root, appid, "library_600x900.jpg", "library_capsule.jpg", "header.jpg"),
        "backdrop": art(root, appid, "library_hero.jpg", "header.jpg", "library_600x900.jpg"),
    } for appid in order]


def available(home=None):
    return find_root(home) is not None


def run_command(steam_app, appid):
    """The command that starts a game through the Steam shortcut in apps.json:
    the same Flatpak (or steam binary), with steam://rungameid/<appid>."""
    launch = list((steam_app or {}).get("launch") or [])
    if len(launch) >= 3 and launch[0] == "flatpak" and launch[1] == "run":
        return launch[:3] + [f"steam://rungameid/{appid}"]
    return [launch[0] if launch else "steam", f"steam://rungameid/{appid}"]
