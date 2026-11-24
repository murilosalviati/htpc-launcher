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
  * "gamepad_activity": a button was pressed, at most once a minute;
  * "tv_off": the launcher's "Turn off TV" button.

After "tv_off" the next button press is sent right away (not up to a minute
later), so the gamepad can wake the TV again at once; the launcher leaves a
marker file for the controller service to see. The automation ignores
activity for a few seconds after the TV goes off, so the press on the button
itself does not turn it back on.

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

from . import __version__, config, paths

log = logging.getLogger("htpc-controller")

ACTIVITY_EVERY = 60.0   # seconds between "gamepad_activity" events
TIMEOUT = 5


def tv_off_marker():
    return paths.data_dir() / "tv-off"


def webhook_url(cfg):
    """The webhook to call, or None when Home Assistant is not set up (or turned off)."""
    ha = (cfg or {}).get("home_assistant") or {}
    if not ha.get("enabled", True) or not ha.get("url") or not ha.get("webhook_id"):
        return None
    return f"{ha['url'].rstrip('/')}/api/webhook/{ha['webhook_id']}"


def send(cfg, event, gamepad="", post=None, background=True):
    """Fire one event; returns False when Home Assistant is not set up."""
    url = webhook_url(cfg)
    if not url:
        return False
    payload = {"event": event, "gamepad": gamepad, "host": socket.gethostname()}
    post = post or http_post

    def work():
        try:
            post(url, payload)
            log.info("home assistant: %s %s", event, gamepad)
        except Exception as e:  # noqa: BLE001
            log.warning("home assistant: %s not sent: %s", event, e)

    if background:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return True


def turn_tv_off(cfg):
    """The launcher's button. Leaves the marker so the next press wakes the TV at once."""
    if not webhook_url(cfg):
        return False
    try:
        marker = tv_off_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()))
    except OSError as e:
        log.warning("could not leave the tv-off marker: %s", e)
    return send(cfg, "tv_off")


def http_post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.status


class HomeAssistant:
    def __init__(self, gamepads, settings=None, post=None, clock=time.monotonic, background=True,
                 marker=tv_off_marker):
        self.gamepads = gamepads
        self.settings = settings or (lambda: config.load()[0])
        self.post = post
        self.clock = clock
        self.background = background
        self.pads = None
        self.last_activity = -ACTIVITY_EVERY
        self.last_sent_wall = 0.0   # wall clock, to compare with the tv-off marker
        self.marker = marker

    def _send(self, event, gamepad=""):
        try:
            cfg = self.settings()
        except Exception:  # noqa: BLE001 - a broken apps.json must not stop the service
            return
        send(cfg, event, gamepad, post=self.post, background=self.background)

    def _tv_turned_off_since_last_send(self):
        try:
            when = self.marker().stat().st_mtime
        except OSError:
            return False
        return when > self.last_sent_wall

    def button(self, event):
        """Called for every gamepad event; only presses count."""
        if event.kind != "button" or not event.value:
            return
        now = self.clock()
        if now - self.last_activity < ACTIVITY_EVERY and not self._tv_turned_off_since_last_send():
            return
        self.last_activity = now
        self.last_sent_wall = time.time()
        self._send("gamepad_activity", self._name(event.device))

    def tick(self):
        now = Counter(self.gamepads.connected())
        if self.pads is not None:
            for name in (now - self.pads).elements():
                self.last_activity = self.clock()  # this already says "someone is here"
                self.last_sent_wall = time.time()
                self._send("gamepad_connected", name)
        self.pads = now

    def _name(self, device):
        dev = getattr(self.gamepads, "devs", {}).get(device)
        return getattr(dev, "name", "") if dev is not None else ""
