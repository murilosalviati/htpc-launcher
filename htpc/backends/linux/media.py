# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Pausing media on Linux through MPRIS (the D-Bus interface media players expose)."""

import logging

from ..base import Media
from .dbus import DBusAddress, DBusClient

log = logging.getLogger("htpc")

PLAYER_TIMEOUT = 0.5   # seconds per player: a stuck one must not hold up the others
PREFIX = "org.mpris.MediaPlayer2."


def _player(name):
    return DBusAddress("/org/mpris/MediaPlayer2", bus_name=name, interface="org.mpris.MediaPlayer2.Player")


class MprisMedia(Media):
    def __init__(self):
        self.dbus = DBusClient("SESSION")

    def _statuses(self):
        """[(bus name, "Playing" / "Paused" / "Stopped")] of every player that answers.
        Raises when the bus itself can't be reached."""
        found = []
        for name in self.dbus.names():
            if not name.startswith(PREFIX):
                continue
            try:
                found.append((name, self.dbus.get(_player(name), "PlaybackStatus", PLAYER_TIMEOUT)))
            except Exception as e:  # noqa: BLE001 - one broken player must not hide the rest
                log.debug("no status from %s: %s", name, e)
        return found

    def playback(self):
        try:
            statuses = {status for _name, status in self._statuses()}
        except Exception as e:  # noqa: BLE001 - bus gone
            log.debug("playback: %s", e)
            return None
        if "Playing" in statuses:
            return "playing"
        if "Paused" in statuses:
            return "paused"
        return "stopped"

    def pause_all(self):
        paused = []
        for name, status in self._statuses():
            if status != "Playing":
                continue
            try:
                self.dbus.call(_player(name), "Pause", timeout=PLAYER_TIMEOUT)
                paused.append(name)
            except Exception as e:  # noqa: BLE001 - one broken player must not block the rest
                log.debug("could not pause %s: %s", name, e)
        return paused
