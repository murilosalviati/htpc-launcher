import pytest

pytest.importorskip("jeepney")

from htpc.backends.linux.media import MprisMedia  # noqa: E402
from htpc.backends.linux.windows import ExtensionWindowControl  # noqa: E402


class FakeClient:
    """Stands in for DBusClient: players by bus name, with their status."""

    def __init__(self, players, broken=()):
        self.players, self.broken, self.paused = players, set(broken), []

    def names(self, timeout=2):
        return ["org.freedesktop.DBus", *self.players]

    def get(self, address, name, timeout=2):
        if address.bus_name in self.broken:
            raise TimeoutError("stuck player")
        return self.players[address.bus_name]

    def call(self, address, method, signature=None, body=(), timeout=2):
        self.paused.append(address.bus_name)
        return ()


def media(players, broken=()):
    m = MprisMedia()
    m.dbus = FakeClient(players, broken)
    return m


VLC, MPV = "org.mpris.MediaPlayer2.vlc", "org.mpris.MediaPlayer2.mpv"


def test_playback_is_playing_if_any_player_plays():
    assert media({VLC: "Paused", MPV: "Playing"}).playback() == "playing"
    assert media({VLC: "Paused"}).playback() == "paused"
    assert media({}).playback() == "stopped"


def test_pause_all_pauses_only_what_plays_and_skips_a_stuck_player():
    m = media({VLC: "Playing", MPV: "Playing"}, broken=[MPV])
    assert m.pause_all() == [VLC] and m.dbus.paused == [VLC]


def test_playback_is_unknown_without_a_bus():
    m = MprisMedia()

    class NoBus:
        def names(self, timeout=2):
            raise ConnectionRefusedError("no session bus")

    m.dbus = NoBus()
    assert m.playback() is None


def test_the_extension_answers_none_when_it_cannot_be_reached():
    w = ExtensionWindowControl()

    class Gone:
        def call(self, *args, **kwargs):
            raise TimeoutError("GNOME Shell busy")

    w.dbus = Gone()
    assert w.windows() is None and w.show_launcher() is False and w.close("x") == 0
