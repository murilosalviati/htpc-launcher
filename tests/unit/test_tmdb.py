import json
import urllib.parse

from htpc import jellyfin, tmdb

SHORT = {"tmdb": {"api_key": "a" * 32}}
LONG = {"tmdb": {"api_key": "eyJ" + "x" * 200}}


class Tmdb:
    def __init__(self):
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        parts = urllib.parse.urlsplit(url)
        page = int(dict(urllib.parse.parse_qsl(parts.query)).get("page", 1))
        if parts.path == "/3/trending/movie/week":
            return {"results": [{"id": 10 * page + n} for n in range(2)]}
        if parts.path == "/3/trending/tv/week":
            return {"results": [{"id": 100 * page}]}
        if parts.path == "/3/movie/popular":
            return {"results": [{"id": 10}, {"id": 999}]}
        if parts.path == "/3/tv/popular":
            return {"results": []}
        if parts.path == "/3/trending/all/week":
            return {"results": [{}] * 20}
        raise AssertionError(url)


def test_short_key_goes_in_the_query_long_token_in_a_header():
    t = Tmdb()
    tmdb.test(SHORT, t)
    url, headers = t.calls[0]
    assert "api_key=" + "a" * 32 in url and "Authorization" not in headers
    tmdb.test(LONG, t)
    url, headers = t.calls[1]
    assert "api_key" not in url and headers["Authorization"].startswith("Bearer eyJ")


def test_ranking_interleaves_films_and_series_then_popular_without_repeats():
    r = tmdb.ranking(SHORT, Tmdb())
    assert r[:4] == [("movie", "10"), ("tv", "100"), ("movie", "11"), ("tv", "200")]
    assert r.count(("movie", "10")) == 1 and r[-1] == ("movie", "999")


LIB = {"Items": [
    {"Id": "a", "Type": "Movie", "Name": "Popular Film", "ProviderIds": {"Tmdb": "11"}, "ImageTags": {"Primary": "p"}},
    {"Id": "b", "Type": "Series", "Name": "Trending Show", "ProviderIds": {"tmdb": "200"}, "ChildCount": 3},
    {"Id": "c", "Type": "Movie", "Name": "Not trending", "ProviderIds": {"Tmdb": "5"}},
    {"Id": "d", "Type": "Movie", "Name": "No id"},
]}
JF = {"jellyfin": {"url": "http://jf", "api_key": "k", "user_id": "u"}}


def jf_get(url, key):
    assert "/Users/u/Items?" in url and "ProviderIds" in url and "Recursive=true" in url
    return json.dumps(LIB).encode()


def test_explore_keeps_tmdbs_order_and_only_whats_in_the_library():
    ranking = [("movie", "10"), ("tv", "200"), ("movie", "11"), ("tv", "999")]
    items = jellyfin.explore(JF, ranking, jf_get)
    assert [i["title"] for i in items] == ["Trending Show", "Popular Film"]
    assert items[0]["new_count"] is None   # not "3 new episodes" in Explore


def test_a_film_and_a_series_with_the_same_number_are_not_mixed_up():
    index = jellyfin.library(JF, jf_get)
    assert ("movie", "11") in index and ("tv", "11") not in index and ("tv", "200") in index
