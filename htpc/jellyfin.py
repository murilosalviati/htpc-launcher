# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""What was added to Jellyfin lately and what is half watched, for the row above the apps.

Configured with a "jellyfin" entry in apps.json:

    "jellyfin": {"url": "http://localhost:8096", "api_key": "...", "user_id": "..."}

The API key comes from Jellyfin's Dashboard → API Keys. "user_id" chooses whose
library and "latest" list it is (Settings → Jellyfin → User); without it the
first administrator is used. "enabled": false hides the row without forgetting
the rest.

Everything here blocks (HTTP): the launcher calls it off the screen's thread.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

TIMEOUT = 6
LATEST_LIMIT = 25
VIDEO_TYPES = "Movie,Episode,Series"
POSTER_HEIGHT = 540      # px asked of Jellyfin for posters (2:3)
BACKDROP_WIDTH = 1280    # px asked for the wide card's picture (16:9)


def settings(cfg):
    return (cfg or {}).get("jellyfin") or {}


def ready(cfg):
    """Is the row switched on and set up (address and key)?"""
    j = settings(cfg)
    return bool(j.get("enabled", True) and j.get("url") and j.get("api_key"))


def _auth(api_key):
    return (f'MediaBrowser Client="HTPC Launcher", Device="HTPC", DeviceId="htpc-launcher", '
            f'Version="{__version__}", Token="{api_key}"')


def http_get(url, api_key):
    """The raw bytes at url (JSON or an image)."""
    request = urllib.request.Request(url, headers={
        "Authorization": _auth(api_key), "X-Emby-Token": api_key,
        "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def _base(cfg):
    return settings(cfg)["url"].rstrip("/")


def _json(cfg, path, query=None, get=None):
    url = _base(cfg) + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return json.loads((get or http_get)(url, settings(cfg)["api_key"]).decode("utf-8"))


def users(cfg, get=None):
    """[(id, name, is_admin)] of the server's enabled users, administrators first."""
    found = []
    for u in _json(cfg, "/Users", get=get):
        policy = u.get("Policy") or {}
        if policy.get("IsDisabled"):
            continue
        found.append((u.get("Id"), u.get("Name") or "?", bool(policy.get("IsAdministrator"))))
    return sorted(found, key=lambda u: (not u[2], u[1].lower()))


def user_id(cfg, get=None):
    """The configured user, else the first administrator (else the first user)."""
    chosen = settings(cfg).get("user_id")
    if chosen:
        return chosen
    found = users(cfg, get)
    if not found:
        raise LookupError("no users on the Jellyfin server")
    return found[0][0]


def image_url(cfg, item_id, kind="Primary", tag=None, **size):
    """Address of one of an item's pictures (Primary, Backdrop, Thumb)."""
    path = f"/Items/{urllib.parse.quote(item_id)}/Images/{kind}" + ("/0" if kind == "Backdrop" else "")
    query = {"quality": 90, **{k: v for k, v in size.items() if v}}
    if tag:
        query["tag"] = tag
    return _base(cfg) + path + "?" + urllib.parse.urlencode(query)


def _item(cfg, raw):
    """A Jellyfin item, reduced to what a card shows. Episodes come grouped by
    series (Jellyfin does that for "latest"), with how many are new."""
    kind = {"Movie": "movie", "Series": "series", "Season": "series", "Episode": "episode"}.get(raw.get("Type"))
    if kind is None or not raw.get("Id"):
        return None
    series_id = raw.get("SeriesId") or (raw.get("Id") if raw.get("Type") == "Series" else None)
    title = raw.get("Name") or "?"
    if kind != "movie" and raw.get("SeriesName"):
        title = raw["SeriesName"]

    poster = None
    tags = raw.get("ImageTags") or {}
    if kind == "movie" or raw.get("Type") == "Series":
        if tags.get("Primary"):
            poster = image_url(cfg, raw["Id"], "Primary", tags["Primary"], maxHeight=POSTER_HEIGHT)
    elif series_id and raw.get("SeriesPrimaryImageTag"):
        poster = image_url(cfg, series_id, "Primary", raw["SeriesPrimaryImageTag"], maxHeight=POSTER_HEIGHT)
    elif tags.get("Primary"):
        poster = image_url(cfg, raw["Id"], "Primary", tags["Primary"], maxHeight=POSTER_HEIGHT)

    backdrop = None
    if raw.get("BackdropImageTags"):
        backdrop = image_url(cfg, raw["Id"], "Backdrop", raw["BackdropImageTags"][0], maxWidth=BACKDROP_WIDTH)
    elif raw.get("ParentBackdropItemId") and raw.get("ParentBackdropImageTags"):
        backdrop = image_url(cfg, raw["ParentBackdropItemId"], "Backdrop", raw["ParentBackdropImageTags"][0],
                             maxWidth=BACKDROP_WIDTH)

    ticks = raw.get("RunTimeTicks") or 0
    return {
        "id": raw["Id"],
        "kind": kind,
        "title": title,
        "year": raw.get("ProductionYear"),
        "minutes": round(ticks / 600_000_000) if ticks else None,
        "season": raw.get("ParentIndexNumber"),
        "episode": raw.get("IndexNumber"),
        "episode_name": raw.get("Name") if kind == "episode" else None,
        "new_count": raw.get("ChildCount") if kind == "series" else None,
        "progress": _progress(raw),
        "poster": poster,
        "backdrop": backdrop,
    }


def _progress(raw):
    """How far it was watched, 0..100, when it was started and not finished."""
    data = raw.get("UserData") or {}
    pct = data.get("PlayedPercentage")
    if pct is None and data.get("PlaybackPositionTicks") and raw.get("RunTimeTicks"):
        pct = 100 * data["PlaybackPositionTicks"] / raw["RunTimeTicks"]
    return max(0.0, min(100.0, float(pct))) if pct else None


def _user_route(cfg, uid, path, query, get):
    """/Users/{uid}{path}, or on newer servers {path}?userId= (the old route is gone there)."""
    try:
        return _json(cfg, f"/Users/{urllib.parse.quote(uid)}{path}", query, get)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return _json(cfg, path, {**query, "userId": uid}, get)


def latest(cfg, get=None, limit=LATEST_LIMIT, types=VIDEO_TYPES):
    """The newest films and series in the user's libraries, newest first.
    types: "Movie" for films only, "Episode,Series" for series only."""
    uid = user_id(cfg, get)
    query = {"Limit": limit, "IncludeItemTypes": types, "GroupItems": "true",
             "Fields": "ProductionYear,RunTimeTicks,ChildCount,ParentId",
             "EnableImageTypes": "Primary,Backdrop,Thumb", "ImageTypeLimit": 1}
    raw = _user_route(cfg, uid, "/Items/Latest", query, get)
    items = [_item(cfg, r) for r in raw or []]
    return [i for i in items if i]


def resume(cfg, get=None, limit=LATEST_LIMIT):
    """What the user stopped in the middle of, most recently watched first (films
    and episodes, each with its progress)."""
    uid = user_id(cfg, get)
    query = {"Limit": limit, "MediaTypes": "Video", "IncludeItemTypes": "Movie,Episode",
             "Fields": "ProductionYear,RunTimeTicks,ParentId",
             "EnableImageTypes": "Primary,Backdrop,Thumb", "ImageTypeLimit": 1, "EnableUserData": "true"}
    raw = _user_route(cfg, uid, "/Items/Resume", query, get)
    items = [_item(cfg, r) for r in (raw or {}).get("Items", [])]
    return [i for i in items if i]


def library(cfg, get=None):
    """{("movie" | "tv", tmdb id): raw item} for every film and series the user
    can see, from the TMDB ids Jellyfin keeps for them."""
    uid = user_id(cfg, get)
    query = {"Recursive": "true", "IncludeItemTypes": "Movie,Series",
             "Fields": "ProviderIds,ProductionYear,RunTimeTicks,ChildCount",
             "EnableImageTypes": "Primary,Backdrop,Thumb", "ImageTypeLimit": 1,
             "EnableTotalRecordCount": "false", "EnableUserData": "false"}
    raw = _user_route(cfg, uid, "/Items", query, get)
    index = {}
    for item in (raw or {}).get("Items", []):
        ids = {k.lower(): v for k, v in (item.get("ProviderIds") or {}).items()}
        if ids.get("tmdb"):
            index.setdefault(("movie" if item.get("Type") == "Movie" else "tv", str(ids["tmdb"])), item)
    return index


def explore(cfg, ranking, get=None, limit=LATEST_LIMIT):
    """What is popular (ranking: [(kind, tmdb id)] best first, from tmdb.py)
    and is in the library, in that order."""
    index = library(cfg, get)
    found = []
    for key in ranking:
        raw = index.get(key)
        if raw is not None:
            item = _item(cfg, raw)
            if item:
                item["new_count"] = None   # "Explore" is not about what's new
                found.append(item)
            if len(found) >= limit:
                break
    return found


def image(cfg, url, get=None):
    """An image's bytes (url from latest())."""
    return (get or http_get)(url, settings(cfg)["api_key"])


def test(cfg, get=None):
    """For Settings → Test: the server's name and version, and how many new items."""
    info = _json(cfg, "/System/Info", get=get)
    return info.get("ServerName") or "Jellyfin", info.get("Version") or "", len(latest(cfg, get))
