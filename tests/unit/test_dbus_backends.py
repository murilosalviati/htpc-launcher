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


# --- Bluetooth pairing: our own agent, and one retry ---------------------------------

def test_agent_answers_bluez_like_a_device_without_screen_or_keys():
    from jeepney import DBusAddress as Addr, MessageType, new_method_call
    from htpc.backends.linux import bluetooth as bt
    ours = Addr(bt.AGENT_PATH, bus_name=":1.5", interface="org.bluez.Agent1")
    reply = bt.agent_reply(new_method_call(ours, "RequestConfirmation", "ou", ("/org/bluez/hci0/dev_X", 1234)))
    assert reply.header.message_type == MessageType.method_return
    pin = bt.agent_reply(new_method_call(ours, "RequestPinCode", "o", ("/x",)))
    assert pin.body == ("0000",)
    other = Addr("/somewhere/else", bus_name=":1.5", interface="org.bluez.Agent1")
    assert bt.agent_reply(new_method_call(other, "RequestConfirmation", "ou", ("/x", 1))) is None
    assert bt.agent_reply(new_method_call(ours, "Weird", None, ())).header.message_type == MessageType.error


def _bluez(paired=False, fail=()):
    from htpc.backends.linux import bluetooth as bt
    b = bt.BluezBluetooth.__new__(bt.BluezBluetooth)
    b.calls, failures = [], list(fail)
    b.dbus = type("D", (), {"bus": "SYSTEM"})()
    path = "/org/bluez/hci0/dev_AA"
    b._path = lambda address: path
    b._objects = lambda: {path: {bt.DEVICE: {"Paired": paired, "Connected": False}}}

    def call(p, interface, method, signature=None, body=(), timeout=None):
        b.calls.append(method)
        if method == "Pair" and failures:
            raise RuntimeError(failures.pop(0))
    b._call = call
    b._set = lambda *a: b.calls.append("Set")
    return b


class Agent:
    made = []

    def __init__(self, bus):
        self.closed = False
        Agent.made.append(self)

    def close(self):
        self.closed = True


def test_pair_registers_its_agent_and_retries_once_when_refused():
    b = _bluez(fail=["[org.bluez.Error.AuthenticationFailed] ('Authentication Failed',)"])
    Agent.made = []
    b.pair("AA", agent=Agent, sleep=lambda s: None)
    assert b.calls == ["Pair", "Pair", "Set", "Connect"]
    assert len(Agent.made) == 1 and Agent.made[0].closed


def test_other_errors_are_not_retried_and_the_agent_still_goes():
    import pytest
    b = _bluez(fail=["[org.bluez.Error.AlreadyExists]"])
    Agent.made = []
    with pytest.raises(RuntimeError):
        b.pair("AA", agent=Agent, sleep=lambda s: None)
    assert b.calls == ["Pair"] and Agent.made[0].closed


def test_without_an_agent_it_still_pairs():
    def broken(bus):
        raise OSError("no system bus")
    b = _bluez()
    b.pair("AA", agent=broken, sleep=lambda s: None)
    assert b.calls == ["Pair", "Set", "Connect"]
