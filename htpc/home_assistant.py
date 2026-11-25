# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Tell Home Assistant when the gamepad is used, so it can wake the TV.

The controller service calls this; Home Assistant does the rest in an
automation triggered by a webhook (for example: if the TV is off, turn it on,
then switch it to the HTPC's HDMI input). Configured in apps.json:

    "home_assistant": {
        "url": "http://192.168.0.10:8123",
        "webhook_id": "htpc-gamepad-...",
        "token": "<long-lived access token>",     (optional, see TvGate)
        "tv_entity": "media_player.living_room_tv", (optional, see TvGate)
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

    def wake(self, event):
        """A press while the TV is off: always sent, whatever the once-a-minute limit."""
        self.last_activity = self.clock()
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


# --- the TV's state, read from Home Assistant -------------------------------------
#
# With a long-lived access token ("token") and the TV's entity ("tv_entity") in
# the same "home_assistant" entry, the controller service asks Home Assistant
# for the TV's state every few seconds. While the TV is off, gamepad input is
# not used for anything (neither the launcher nor the shortcuts): the first
# press only wakes the TV, through the same webhook. The service writes what it
# knows to a small file the launcher reads ("tv-gate").

STATE_EVERY = 3.0     # seconds between state checks
WAKE_RETRY = 8.0      # a press this long after the last wake asks again
GATE_FRESH = 10.0     # the launcher ignores a gate file older than this
GIVE_UP_WAKES = 3     # this many wakes without the TV turning on...
GIVE_UP_WINDOW = 60.0 # ...within this many seconds: Home Assistant's "off" is not trusted
DISTRUST_FOR = 600.0  # for this long (or until it reports the TV on): nothing is blocked
OFF_STATES = {"off", "standby"}


def api_ready(cfg):
    """Can we read states? (enabled, address, token and TV entity set)"""
    ha = (cfg or {}).get("home_assistant") or {}
    return bool(ha.get("enabled", True) and ha.get("url") and ha.get("token") and ha.get("tv_entity"))


def http_get(url, token):
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _api(cfg, path, get=None):
    ha = cfg["home_assistant"]
    return (get or http_get)(f"{ha['url'].rstrip('/')}/api/{path}", ha["token"])


def fetch_tv_state(cfg, get=None):
    """"on", "off", or None when unknown (not set up, unavailable, unreachable)."""
    if not api_ready(cfg):
        return None
    state = _api(cfg, "states/" + cfg["home_assistant"]["tv_entity"], get).get("state")
    if state in OFF_STATES:
        return "off"
    if state in ("unavailable", "unknown", None):
        return None
    return "on"


def media_players(cfg, get=None):
    """[(entity_id, friendly name)] of the media players Home Assistant knows."""
    states = _api(cfg, "states", get)
    found = [(s["entity_id"], (s.get("attributes") or {}).get("friendly_name") or s["entity_id"])
             for s in states if str(s.get("entity_id", "")).startswith("media_player.")]
    return sorted(found, key=lambda item: item[1].lower())


def gate_file():
    return paths.data_dir() / "tv-gate"


def write_gate(blocked, path=None, now=time.time):
    path = path or gate_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"blocked": bool(blocked), "at": now()}))
        tmp.replace(path)
    except OSError as e:
        log.warning("could not write the tv gate: %s", e)


def input_blocked(path=None, now=time.time):
    """For the launcher: is the TV off (so gamepad input must be ignored)?
    A missing, broken or old file (the service is not running) means no."""
    try:
        data = json.loads((path or gate_file()).read_text())
    except (OSError, ValueError):
        return False
    return bool(data.get("blocked")) and now() - float(data.get("at", 0)) < GATE_FRESH


def is_press(event, dead_zone=0.55):
    if event.kind == "button":
        return bool(event.value)
    if event.kind == "axis":
        return abs(event.value) > dead_zone
    return False


class TvGate:
    """In the controller service: keeps the TV's state and swallows input while it is off."""

    def __init__(self, settings, send_wake, get=None, clock=time.monotonic, gate=write_gate):
        self.settings = settings
        self.send_wake = send_wake      # called with the event that should wake the TV
        self.get = get
        self.clock = clock
        self.gate = gate
        self.state = None               # "on" / "off" / None
        self.last_wake = None
        self.wakes = []                 # times of the recent wake requests
        self.distrust_until = None      # Home Assistant says "off" but the TV doesn't wake up
        self._lock = threading.Lock()

    def check(self):
        """Ask Home Assistant once (runs in its own thread in the service)."""
        try:
            cfg = self.settings()
            state = fetch_tv_state(cfg, self.get)
        except Exception as e:  # noqa: BLE001 - unreachable: we just don't know
            log.debug("tv state: %s", e)
            state = None
        with self._lock:
            if state != self.state:
                log.info("tv: %s", state or "unknown")
            self.state = state
            if state != "off":
                self.last_wake = None
                self.wakes = []
                self.distrust_until = None
            blocked = state == "off" and not self._distrusted()
        self.gate(blocked)

    def _distrusted(self):
        return self.distrust_until is not None and self.clock() < self.distrust_until

    def run_forever(self):
        while True:
            self.check()
            time.sleep(STATE_EVERY)

    def start(self):
        threading.Thread(target=self.run_forever, daemon=True, name="tv-state").start()

    def blocks(self, event):
        """True when the event must not be used. The first press while the TV is
        off wakes it (again after WAKE_RETRY if it is still off)."""
        with self._lock:
            if self.state != "off" or self._distrusted():
                return False
            if not is_press(event):
                return False   # releases and a stick going back to the middle are harmless
            now = self.clock()
            wake = self.last_wake is None or now - self.last_wake >= WAKE_RETRY
            if wake:
                self.last_wake = now
                self.wakes = [t for t in self.wakes if now - t < GIVE_UP_WINDOW] + [now]
                if len(self.wakes) > GIVE_UP_WAKES:
                    # Woken several times and still "off": Home Assistant has lost the
                    # TV (a new IP address, the integration down...). Don't lock the
                    # gamepad out because of that.
                    log.warning("tv still off for Home Assistant after %d wakes: not blocking the "
                                "gamepad for %d minutes", GIVE_UP_WAKES, DISTRUST_FOR // 60)
                    self.distrust_until = now + DISTRUST_FOR
                    self.wakes = []
                    wake = False
        if self._distrusted():
            self.gate(False)
            return False
        if wake:
            log.info("tv is off: this press only wakes it")
            self.send_wake(event)
        return True


# --- app and media events, for "cinema mode" automations ----------------------------
#
# Optional, on a webhook of their own ("events_webhook_id"): a Home Assistant
# webhook only triggers one automation, and the gamepad's one must not react to
# these. Events: app_opened / app_closed (an app from apps.json got or lost its
# windows) and media_playing / media_paused / media_stopped (MPRIS, all players
# together). Each carries "app": the app in front, by its name in apps.json.

EVENTS_EVERY = 2.0


def events_url(cfg):
    ha = (cfg or {}).get("home_assistant") or {}
    if not ha.get("enabled", True) or not ha.get("url") or not ha.get("events_webhook_id"):
        return None
    return f"{ha['url'].rstrip('/')}/api/webhook/{ha['events_webhook_id']}"


class AppEvents:
    """In the controller service: watches the apps and the media players."""

    def __init__(self, windows, media, settings, post=None, clock=time.monotonic, background=True):
        from .shortcuts import app_for_window, is_launcher
        self._app_for_window, self._is_launcher = app_for_window, is_launcher
        self.windows = windows
        self.media = media
        self.settings = settings
        self.post = post or http_post
        self.clock = clock
        self.background = background
        self.running = None     # names of the apps with windows (None: not looked yet)
        self.playback = None
        self.last = None

    def tick(self):
        now = self.clock()
        if self.last is not None and now - self.last < EVENTS_EVERY:
            return
        self.last = now
        cfg = self.settings()
        url = events_url(cfg)
        if url is None:
            self.running = self.playback = None   # start fresh when turned on
            return
        windows = self.windows.windows()
        if windows is None:
            return
        running, front = set(), ""
        for w in windows:
            if self._is_launcher(cfg, w):
                if w.focused:
                    front = "launcher"
                continue
            app = self._app_for_window(cfg, w)
            if app:
                running.add(app["name"])
                if w.focused:
                    front = app["name"]
        playback = self.media.playback()
        if self.running is not None:
            for name in sorted(running - self.running):
                self._send(url, "app_opened", name, front)
            for name in sorted(self.running - running):
                self._send(url, "app_closed", name, front)
        if self.playback is not None and playback is not None and playback != self.playback:
            self._send(url, "media_" + playback, front, front)
        self.running = running
        if playback is not None:
            self.playback = playback

    def _send(self, url, event, app, front):
        payload = {"event": event, "app": app, "front": front, "host": socket.gethostname()}
        log.info("home assistant event: %s (%s)", event, app)

        def go():
            try:
                self.post(url, payload)
            except Exception as e:  # noqa: BLE001
                log.warning("home assistant event %s failed: %s", event, e)

        if self.background:
            threading.Thread(target=go, daemon=True).start()
        else:
            go()
