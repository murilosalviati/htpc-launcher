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

import json
import urllib.parse
import urllib.request

from . import __version__

API = "https://api.themoviedb.org/3"
TIMEOUT = 8
TRENDING_PAGES = 3   # 20 titles a page, per kind
POPULAR_PAGES = 2    # then the most popular, for a longer list to match against


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


def ranking(cfg, get=None):
    """[(kind, tmdb_id)] best first, kind "movie" or "tv": this week's trending
    films and series interleaved, then the most popular ones, without repeats."""
    lists = []
    for kind in ("movie", "tv"):
        found = []
        for page in range(1, TRENDING_PAGES + 1):
            found += [(kind, str(r["id"])) for r in _get(cfg, f"/trending/{kind}/week", {"page": page}, get)
                      .get("results", []) if r.get("id")]
        lists.append(found)
    order = [item for pair in _interleave(*lists) for item in pair]
    for kind in ("movie", "tv"):
        for page in range(1, POPULAR_PAGES + 1):
            order += [(kind, str(r["id"])) for r in _get(cfg, f"/{kind}/popular", {"page": page}, get)
                      .get("results", []) if r.get("id")]
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
