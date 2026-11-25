# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""What is popular this week, from TMDB (The Movie Database), for "Explore".

Only the order comes from TMDB: the launcher keeps the titles that are in your
Jellyfin library (Jellyfin stores each item's TMDB id) and shows those.

Configured with a "tmdb" entry in apps.json:

    "tmdb": {"api_key": "..."}

Either TMDB's short API key (32 characters, sent as ?api_key=) or its long API
Read Access Token (sent as a Bearer token) works. Both are free: themoviedb.org
→ Settings → API. This product uses the TMDB API but is not endorsed or
certified by TMDB.

Everything here blocks (HTTP): the launcher calls it off the screen's thread.
"""

import datetime
import json
import urllib.parse
import urllib.request

from . import __version__

API = "https://api.themoviedb.org/3"
TIMEOUT = 8
TRENDING_PAGES = 3   # 20 titles a page, per kind
AIRING_PAGES = 3     # series with episodes airing this week (new seasons of older series)
NOW_PLAYING_PAGES = 2
RECENT_DAYS = 540    # a trending title counts as new when it came out this recently


def settings(cfg):
    return (cfg or {}).get("tmdb") or {}


def ready(cfg):
    return bool(settings(cfg).get("api_key"))


def http_get(url, headers):
    request = urllib.request.Request(url, headers={**headers, "Accept": "application/json",
                                                   "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(cfg, path, query=None, get=None):
    key = settings(cfg)["api_key"].strip()
    query = dict(query or {})
    headers = {}
    if len(key) > 40:            # the API Read Access Token
        headers["Authorization"] = f"Bearer {key}"
    else:                        # the short API key
        query["api_key"] = key
    url = f"{API}{path}?{urllib.parse.urlencode(query)}"
    return (get or http_get)(url, headers)


def _date(text):
    try:
        return datetime.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _pages(cfg, path, pages, get):
    found = []
    for page in range(1, pages + 1):
        found += [r for r in _get(cfg, path, {"page": page}, get).get("results", []) if r.get("id")]
    return found


def ranking(cfg, get=None, today=None):
    """[(kind, tmdb_id)] best first, kind "movie" or "tv": what is new and
    popular, not just popular. This week's trending films and series that came
    out recently (RECENT_DAYS, or "recent_days" in the tmdb entry), and series
    with a new episode this week, interleaved; then the series airing this week
    and the films in cinemas. No all-time favourites: an old sitcom that is
    trending without new episodes is left out."""
    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=int(settings(cfg).get("recent_days", RECENT_DAYS)))
    airing = _pages(cfg, "/tv/on_the_air", AIRING_PAGES, get)
    airing_ids = {str(r["id"]) for r in airing}

    def new(r, field):
        day = _date(r.get(field))
        return day is not None and since <= day <= today

    movies = [("movie", str(r["id"])) for r in _pages(cfg, "/trending/movie/week", TRENDING_PAGES, get)
              if new(r, "release_date")]
    series = [("tv", str(r["id"])) for r in _pages(cfg, "/trending/tv/week", TRENDING_PAGES, get)
              if new(r, "first_air_date") or str(r["id"]) in airing_ids]
    order = [item for pair in _interleave(movies, series) for item in pair]
    order += [("tv", str(r["id"])) for r in airing]
    order += [("movie", str(r["id"])) for r in _pages(cfg, "/movie/now_playing", NOW_PLAYING_PAGES, get)]
    seen, ranked = set(), []
    for item in order:
        if item not in seen:
            seen.add(item)
            ranked.append(item)
    return ranked


def _interleave(a, b):
    for n in range(max(len(a), len(b))):
        yield tuple(x[n] for x in (a, b) if n < len(x))


def test(cfg, get=None):
    """For Settings → Test: how many trending titles TMDB returned."""
    return len(_get(cfg, "/trending/all/week", get=get).get("results", []))
