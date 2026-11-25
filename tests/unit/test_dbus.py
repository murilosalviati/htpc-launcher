import pytest

pytest.importorskip("jeepney")

from htpc.backends.linux import dbus  # noqa: E402


class FakeConnection:
    opened = 0

    def __init__(self, replies):
        FakeConnection.opened += 1
        self.replies = replies
        self.closed = False

    def send_and_get_reply(self, msg, timeout):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self):
        self.closed = True


@pytest.fixture
def client(monkeypatch):
    replies = []
    connections = []

    def open_connection(bus):
        conn = FakeConnection(replies)
        connections.append(conn)
        return conn

    monkeypatch.setattr(dbus, "open_dbus_connection", open_connection)
    monkeypatch.setattr(dbus, "unwrap_msg", lambda reply: reply)
    c = dbus.DBusClient("SESSION")
    c.replies, c.connections = replies, connections
    return c


ADDRESS = dbus.DBusAddress("/a", bus_name="org.example", interface="org.example")


def test_the_connection_is_opened_once_and_reused(client):
    client.replies += [("one",), ("two",)]
    assert client.call(ADDRESS, "M") == ("one",)
    assert client.call(ADDRESS, "M") == ("two",)
    assert len(client.connections) == 1


def test_a_broken_connection_is_closed_and_the_next_call_reconnects(client):
    client.replies += [ConnectionResetError("bus gone"), ("back",)]
    with pytest.raises(ConnectionResetError):
        client.call(ADDRESS, "M")
    assert client.connections[0].closed
    assert client.call(ADDRESS, "M") == ("back",)
    assert len(client.connections) == 2


def test_a_timeout_keeps_the_connection(client):
    client.replies += [TimeoutError(), ("later",)]
    with pytest.raises(TimeoutError):
        client.call(ADDRESS, "M")
    assert client.call(ADDRESS, "M") == ("later",)
    assert len(client.connections) == 1 and not client.connections[0].closed


def test_get_returns_the_plain_property_value(client):
    client.replies.append((("s", "Playing"),))
    assert client.get(ADDRESS, "PlaybackStatus") == "Playing"
