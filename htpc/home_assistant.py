# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Tell Home Assistant when the gamepad is used, so it can wake the TV.

The controller service calls this; Home Assistant does the rest in an
automation triggered by a webhook (for example: if the TV is off, turn it on,
then switch it to the HTPC's HDMI input). Configured in apps.json:

    "home_assistant": {
        "url": "http://192.168.0.10:8123",
        "webhook_id": "htpc-gamepad-...",
        "enabled": true
    }

Events, sent as JSON {"event": ..., "gamepad": name, "host": hostname}:

  * "gamepad_connected": a gamepad showed up (plugged in, or a wireless one
    turned on);
  * "gamepad_activity": a button was pressed, at most once a minute.

A webhook only accepts calls from the local network by default and needs no
token. Requests run in a thread and never hold up the shortcuts; failures are
only logged.
"""

import json
import logging
import socket
import threading
import time
import urllib.request
from collections import Counter

from . import __version__, config

log = logging.getLogger("htpc-controller")

ACTIVITY_EVERY = 60.0   # seconds between "gamepad_activity" events
TIMEOUT = 5


def http_post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status


class HomeAssistant:
    def __init__(self, gamepads, settings=None, post=http_post, clock=time.monotonic, background=True):
        self.gamepads = gamepads
        self.settings = settings or (lambda: config.load()[0])
        self.post = post
        self.clock = clock
        self.background = background
        self.pads = None
        self.last_activity = -ACTIVITY_EVERY
        self.host = socket.gethostname()

    def _target(self):
        try:
            ha = self.settings().get("home_assistant") or {}
        except Exception:  # noqa: BLE001 - a broken apps.json must not stop the service
            return None
        if not ha.get("enabled", True) or not ha.get("url") or not ha.get("webhook_id"):
            return None
        return f"{ha['url'].rstrip('/')}/api/webhook/{ha['webhook_id']}"

    def _send(self, event, gamepad=""):
        url = self._target()
        if not url:
            return
        payload = {"event": event, "gamepad": gamepad, "host": self.host}

        def work():
            try:
                self.post(url, payload)
                log.info("home assistant: %s %s", event, gamepad)
            except Exception as e:  # noqa: BLE001
                log.warning("home assistant: %s not sent: %s", event, e)

        if self.background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def button(self, event):
        """Called for every gamepad event; only presses count."""
        if event.kind != "button" or not event.value:
            return
        now = self.clock()
        if now - self.last_activity < ACTIVITY_EVERY:
            return
        self.last_activity = now
        self._send("gamepad_activity", self._name(event.device))

    def tick(self):
        now = Counter(self.gamepads.connected())
        if self.pads is not None:
            for name in (now - self.pads).elements():
                self.last_activity = self.clock()  # this already says "someone is here"
                self._send("gamepad_connected", name)
        self.pads = now

    def _name(self, device):
        dev = getattr(self.gamepads, "devs", {}).get(device)
        return getattr(dev, "name", "") if dev is not None else ""
