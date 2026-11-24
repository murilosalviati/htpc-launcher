# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Pausing media on Linux through MPRIS (the D-Bus interface media players expose)."""

import logging

from jeepney import DBusAddress, Properties, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

from ..base import Media

log = logging.getLogger("htpc")


class MprisMedia(Media):
    def __init__(self):
        self.conn = None

    def pause_all(self):
        if self.conn is None:
            self.conn = open_dbus_connection(bus="SESSION")
        names = unwrap_msg(self.conn.send_and_get_reply(message_bus.ListNames(), timeout=2))[0]
        paused = []
        for name in names:
            if not name.startswith("org.mpris.MediaPlayer2."):
                continue
            player = DBusAddress("/org/mpris/MediaPlayer2", bus_name=name,
                                 interface="org.mpris.MediaPlayer2.Player")
            try:
                status = unwrap_msg(self.conn.send_and_get_reply(
                    Properties(player).get("PlaybackStatus"), timeout=1))[0][1]
                if status == "Playing":
                    unwrap_msg(self.conn.send_and_get_reply(new_method_call(player, "Pause"), timeout=1))
                    paused.append(name)
            except Exception as e:  # one broken player must not block the rest
                log.debug("could not pause %s: %s", name, e)
        return paused
