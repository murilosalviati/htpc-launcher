# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The Steam games played most recently, for the home screen's "Games" tab.

Read from Steam's own files, without its API or an account key:

  * userdata/<user>/config/localconfig.vdf: when each game was last played
    ("LastPlayed") and for how long ("Playtime", minutes);
  * steamapps/appmanifest_<id>.acf, in every library folder: which games are
    installed, and their names;
  * appcache/librarycache: the cover art Steam already downloaded.

Games that are not installed here count too: an HTPC often only streams them
from another computer (Steam Remote Play). Their names come from the Steam
store, once per game, kept in ~/.cache/htpc-launcher/steam-apps.json; their
covers from Steam's cache or, failing that, Steam's image servers.

Works with the Flatpak Steam (~/.var/app/com.valvesoftware.Steam) and a
native one. Proton, the Steam runtimes, redistributables and anything the
store doesn't know as a game are left out.
"""

import json
import re
import urllib.request
from pathlib import Path

from . import __version__, paths

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
STORE = "https://store.steampowered.com/api/appdetails?filters=basic&appids={appid}"
CDN = "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/{name}"
GAME_TYPES = {"game", "demo", "mod"}
LOOKUPS_PER_UPDATE = 30   # names asked of the store at most per update (the rest next time)
TIMEOUT = 6


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
    """{appid: name} of what is installed (games, and tools such as Proton)."""
    games = {}
    for folder in library_folders(root):
        for manifest in (folder / "steamapps").glob("appmanifest_*.acf"):
            state = _get(_read(manifest), "AppState") or {}
            appid, name = _get(state, "appid"), _get(state, "name")
            if appid and name:   # tools too (Proton...): recent_games leaves them out by name
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


def http_get(url):
    request = urllib.request.Request(url, headers={"User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def store_lookup(appid, get=None):
    """(name, type) from the Steam store, or None when it doesn't know the app."""
    data = json.loads((get or http_get)(STORE.format(appid=appid)).decode("utf-8")).get(str(appid)) or {}
    if not data.get("success"):
        return None
    info = data.get("data") or {}
    return (info.get("name"), info.get("type")) if info.get("name") else None


class Names:
    """appid -> (name, type), from the store, kept on disk. A failed lookup is
    not kept (it is tried again next time); an unknown app is, as None."""

    def __init__(self, path=None, lookup=store_lookup):
        self.path = Path(path) if path else paths.cache_dir() / "steam-apps.json"
        self.lookup = lookup
        try:
            self.known = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.known = {}
        self.changed = False
        self.asked = 0

    def get(self, appid):
        if appid in self.known:
            found = self.known[appid]
            return tuple(found) if found else None
        if self.asked >= LOOKUPS_PER_UPDATE:
            return None
        self.asked += 1
        try:
            found = self.lookup(appid)
        except Exception:  # noqa: BLE001 - no internet, rate limit: try again next time
            return None
        self.known[appid] = list(found) if found else None
        self.changed = True
        return found

    def save(self):
        if not self.changed:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.known))
            tmp.replace(self.path)
        except OSError:
            pass


def recent_games(home=None, limit=RECENT_LIMIT, names=None):
    """The games played most recently, installed here or not (streamed).
    Never played: left out."""
    root = find_root(home)
    if root is None:
        return []
    names = names or Names()
    local, times = installed(root), played(root)
    found = []
    for appid in sorted(times, key=lambda a: times[a][0], reverse=True):
        if appid in local:
            title, installed_here = local[appid], True
        else:
            known = names.get(appid)
            if not known or (known[1] or "game") not in GAME_TYPES:
                continue
            title, installed_here = known[0], False
        if NOT_GAMES.match(title):
            continue
        found.append({
            "id": f"steam:{appid}",
            "kind": "game",
            "appid": appid,
            "title": title,
            "installed": installed_here,
            "last_played": times[appid][0],
            "minutes": times[appid][1],
            "poster": art(root, appid, "library_600x900.jpg", "library_capsule.jpg", "header.jpg")
            or CDN.format(appid=appid, name="library_600x900.jpg"),
            "backdrop": art(root, appid, "library_hero.jpg", "header.jpg", "library_600x900.jpg")
            or CDN.format(appid=appid, name="header.jpg"),
        })
        if len(found) >= limit:
            break
    names.save()
    return found


def image(url, get=None):
    """A cover's bytes: a file in Steam's cache, or from Steam's image servers."""
    if url.startswith("/"):
        with open(url, "rb") as f:
            return f.read()
    return (get or http_get)(url)


def available(home=None):
    return find_root(home) is not None


def run_command(steam_app, appid, installed=True):
    """The command that opens a game through the Steam shortcut in apps.json
    (the same Flatpak, or steam binary): an installed game starts
    (steam://rungameid/<appid>); one that isn't opens its page in Steam, whose
    button streams it from the computer that has it."""
    url = f"steam://rungameid/{appid}" if installed else f"steam://nav/games/details/{appid}"
    launch = list((steam_app or {}).get("launch") or [])
    if len(launch) >= 3 and launch[0] == "flatpak" and launch[1] == "run":
        return launch[:3] + [url]
    return [launch[0] if launch else "steam", url]
