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
DISCOVER_PAGES = 5   # then the most popular recent ones beyond this week's trends, to match more of a library
AIRED_DAYS = 45      # a series with an episode this recent counts as new...
SERIES_MAX_YEARS = 8 # ...if it premiered this recently: SNL or SpongeBob always have a new
                     # episode, and they are not news ("series_max_years" in the tmdb entry)
NOT_NEW_GENRES = {10762, 10763, 10766, 10767}   # TMDB's Kids, News, Soap and Talk series
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


def _pages(cfg, path, pages, get, query=None):
    found = []
    for page in range(1, pages + 1):
        found += [r for r in _get(cfg, path, {**(query or {}), "page": page}, get).get("results", []) if r.get("id")]
    return found


def ranking(cfg, get=None, today=None):
    """[(kind, tmdb_id)] best first, kind "movie" or "tv": what is new and
    popular, not just popular. This week's trending films and series that came
    out recently (RECENT_DAYS, or "recent_days" in the tmdb entry), and series
    with a new episode this week, interleaved; then the series airing this week,
    the films in cinemas, and the most popular series with an episode in the
    last AIRED_DAYS and films from the window. No all-time favourites: an old
    sitcom that is trending without new episodes is left out."""
    today = today or datetime.date.today()
    since = today - datetime.timedelta(days=int(settings(cfg).get("recent_days", RECENT_DAYS)))
    oldest = today - datetime.timedelta(days=365 * int(settings(cfg).get("series_max_years", SERIES_MAX_YEARS)))

    def new(r, field):
        day = _date(r.get(field))
        return day is not None and since <= day <= today

    def series_ok(r):
        """A series with a new episode, that is not a decades-long show."""
        day = _date(r.get("first_air_date"))
        return (day is not None and day >= oldest
                and not NOT_NEW_GENRES & set(r.get("genre_ids") or []))

    airing = [r for r in _pages(cfg, "/tv/on_the_air", AIRING_PAGES, get) if series_ok(r)]
    airing_ids = {str(r["id"]) for r in airing}

    movies = [("movie", str(r["id"])) for r in _pages(cfg, "/trending/movie/week", TRENDING_PAGES, get)
              if new(r, "release_date")]
    series = [("tv", str(r["id"])) for r in _pages(cfg, "/trending/tv/week", TRENDING_PAGES, get)
              if new(r, "first_air_date") or str(r["id"]) in airing_ids]
    order = [item for pair in _interleave(movies, series) for item in pair]
    order += [("tv", str(r["id"])) for r in airing]
    order += [("movie", str(r["id"])) for r in _pages(cfg, "/movie/now_playing", NOW_PLAYING_PAGES, get)]
    # Beyond this week: the most popular series with a recent episode and films
    # from the window, so more of a library finds a match.
    recently = (today - datetime.timedelta(days=AIRED_DAYS)).isoformat()
    tv = [r for r in _pages(cfg, "/discover/tv", DISCOVER_PAGES, get, {
        "sort_by": "popularity.desc", "air_date.gte": recently, "air_date.lte": today.isoformat()})
          if series_ok(r)]
    films = _pages(cfg, "/discover/movie", DISCOVER_PAGES, get, {
        "sort_by": "popularity.desc", "primary_release_date.gte": since.isoformat(),
        "primary_release_date.lte": today.isoformat()})
    order += [item for pair in _interleave([("movie", str(r["id"])) for r in films],
                                           [("tv", str(r["id"])) for r in tv]) for item in pair]
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
