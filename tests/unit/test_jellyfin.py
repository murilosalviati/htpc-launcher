import io
import json
import urllib.error
import urllib.parse

import pytest

from htpc import jellyfin

CFG = {"jellyfin": {"url": "http://jf:8096/", "api_key": "KEY"}}

USERS = [
    {"Id": "u-kid", "Name": "kid", "Policy": {"IsAdministrator": False}},
    {"Id": "u-old", "Name": "old", "Policy": {"IsAdministrator": True, "IsDisabled": True}},
    {"Id": "u-admin", "Name": "mu", "Policy": {"IsAdministrator": True}},
]

LATEST = [
    {"Id": "m1", "Type": "Movie", "Name": "A Film", "ProductionYear": 2024, "RunTimeTicks": 112 * 600_000_000,
     "ImageTags": {"Primary": "p1"}, "BackdropImageTags": ["b1"]},
    {"Id": "s1", "Type": "Series", "Name": "A Show", "ChildCount": 3, "ImageTags": {"Primary": "p2"}},
    {"Id": "e1", "Type": "Episode", "Name": "Pilot", "SeriesName": "Other Show", "SeriesId": "s2",
     "SeriesPrimaryImageTag": "p3", "ParentIndexNumber": 1, "IndexNumber": 2,
     "ParentBackdropItemId": "s2", "ParentBackdropImageTags": ["b3"]},
    {"Id": "x1", "Type": "MusicAlbum", "Name": "Not video"},
]


class Server:
    def __init__(self, latest_404=False):
        self.calls = []
        self.latest_404 = latest_404

    def __call__(self, url, key):
        self.calls.append((url, key))
        path = urllib.parse.urlsplit(url).path
        if path == "/Users":
            return json.dumps(USERS).encode()
        if path.endswith("/Items/Latest"):
            if self.latest_404 and path.startswith("/Users/"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
            return json.dumps(LATEST).encode()
        if path == "/System/Info":
            return json.dumps({"ServerName": "servidor", "Version": "10.11.0"}).encode()
        return b"\x89PNG..."


def test_ready_needs_address_and_key_and_respects_off():
    assert not jellyfin.ready({})
    assert not jellyfin.ready({"jellyfin": {"url": "http://x"}})
    assert jellyfin.ready(CFG)
    assert not jellyfin.ready({"jellyfin": {**CFG["jellyfin"], "enabled": False}})


def test_users_skip_disabled_and_put_admins_first():
    assert jellyfin.users(CFG, Server()) == [("u-admin", "mu", True), ("u-kid", "kid", False)]


def test_user_id_prefers_the_configured_one():
    assert jellyfin.user_id(CFG, Server()) == "u-admin"
    cfg = {"jellyfin": {**CFG["jellyfin"], "user_id": "u-kid"}}
    server = Server()
    assert jellyfin.user_id(cfg, server) == "u-kid" and server.calls == []


def test_latest_items_are_reduced_to_cards():
    server = Server()
    items = jellyfin.latest(CFG, server)
    assert [i["id"] for i in items] == ["m1", "s1", "e1"]   # the album is left out
    film, show, episode = items
    assert film["kind"] == "movie" and film["year"] == 2024 and film["minutes"] == 112
    assert film["poster"].startswith("http://jf:8096/Items/m1/Images/Primary?")
    assert "/Items/m1/Images/Backdrop/0?" in film["backdrop"]
    assert show["kind"] == "series" and show["new_count"] == 3
    assert episode["title"] == "Other Show" and episode["season"] == 1 and episode["episode"] == 2
    assert "/Items/s2/Images/Primary?" in episode["poster"] and "/Items/s2/Images/Backdrop/0?" in episode["backdrop"]
    url, key = server.calls[-1]
    assert key == "KEY" and "/Users/u-admin/Items/Latest?" in url and "GroupItems=true" in url


def test_latest_falls_back_to_the_newer_route():
    server = Server(latest_404=True)
    assert len(jellyfin.latest(CFG, server)) == 3
    assert "/Items/Latest?" in server.calls[-1][0] and "userId=u-admin" in server.calls[-1][0]


def test_other_errors_are_not_hidden():
    def broken(url, key):
        if "/Latest" in url:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b""))
        return json.dumps(USERS).encode()
    with pytest.raises(urllib.error.HTTPError):
        jellyfin.latest(CFG, broken)


def test_test_reports_server_and_count():
    assert jellyfin.test(CFG, Server()) == ("servidor", "10.11.0", 3)
