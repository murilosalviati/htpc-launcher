# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""One D-Bus connection per object, opened on first use (jeepney, blocking).

Every Linux backend that talks D-Bus (the GNOME extension, MPRIS, Mutter, BlueZ,
NetworkManager) goes through DBusClient, so they all handle a broken bus the
same way:

  * the connection is opened on the first call;
  * a broken connection is closed and dropped, and the next call opens a new one;
  * an error *reply* (the other side said no: DBusErrorResponse) or a timeout (a
    slow or stuck peer) keeps the connection, which is still fine;
  * calls on one client are serialized, so it can be shared between threads.
"""

import threading

from jeepney import DBusAddress, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

__all__ = ["DBusAddress", "DBusClient", "DBusErrorResponse"]


class DBusClient:
    def __init__(self, bus="SESSION"):
        self.bus = bus
        self._conn = None
        self._lock = threading.RLock()

    def send(self, msg, timeout=2):
        """The reply's body (a tuple). Raises when there is no answer."""
        with self._lock:
            try:
                if self._conn is None:
                    self._conn = open_dbus_connection(bus=self.bus)
                return unwrap_msg(self._conn.send_and_get_reply(msg, timeout=timeout))
            except (DBusErrorResponse, TimeoutError):
                raise   # the bus is fine: the peer said no, or is slow
            except Exception:
                self.reset()
                raise

    def call(self, address, method, signature=None, body=(), timeout=2):
        return self.send(new_method_call(address, method, signature, body), timeout)

    def get(self, address, name, timeout=2):
        """One property's plain value (without its D-Bus signature)."""
        return self.send(Properties(address).get(name), timeout)[0][1]

    def names(self, timeout=2):
        """Every name on the bus."""
        return self.send(message_bus.ListNames(), timeout)[0]

    def reset(self):
        """Close the connection; the next call opens a new one."""
        with self._lock:
            conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - already broken
                pass
