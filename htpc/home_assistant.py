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
import re
import logging
import socket
import threading
import time
import urllib.request
from collections import Counter

from . import __version__, config, paths
from .backends.base import STICK_DEAD_ZONE
from .timing import Throttle

log = logging.getLogger("htpc-controller")

ACTIVITY_EVERY = 60.0   # seconds between "gamepad_activity" events
TIMEOUT = 5


def tv_off_marker():
    return paths.data_dir() / "tv-off"


# --- another input (a console on HDMI 2) ----------------------------------------------
#
# "quick_source": {"source": "HDMI 2", "label": "Nintendo Switch"} in the
# home_assistant entry puts a button at the top of the launcher that switches
# the TV to that input. "htpc_source" (remembered on the first switch) is the
# HTPC's own input: while the TV shows another one, the HTPC's gamepads only
# bring it back (the first press goes to the wake webhook, whose automation
# selects the HTPC's input), like when the TV is off.

AWAY_QUIET = 15.0   # seconds after a switch when the HTPC's gamepads don't bring the TV back


def away_marker():
    return paths.data_dir() / "tv-away"


def recently_away(marker=None, now=time.time, quiet=AWAY_QUIET):
    """Did the launcher switch the TV to another input a moment ago? (The press on
    the button itself must not switch it back.)"""
    try:
        return now() - (marker or away_marker()).stat().st_mtime < quiet
    except OSError:
        return False


def tv_sources(cfg, get=None):
    """(the TV's current input, [its inputs]) from Home Assistant."""
    attrs = _api(cfg, "states/" + cfg["home_assistant"]["tv_entity"], get).get("attributes") or {}
    return attrs.get("source"), list(attrs.get("source_list") or [])


def switch_source(cfg, source, post=None, marker=None):
    """Switch the TV to another input; leaves the marker first (see recently_away)."""
    path = marker or away_marker()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()))
    except OSError as e:
        log.warning("could not leave the tv-away marker: %s", e)
    _post(cfg, "services/media_player/select_source",
          {"entity_id": cfg["home_assistant"]["tv_entity"], "source": source}, post)


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
                 marker=tv_off_marker, away=recently_away):
        self.gamepads = gamepads
        self.settings = settings or config.load_quietly
        self.post = post
        self.clock = clock
        self.background = background
        self.pads = None
        self.activity = Throttle(ACTIVITY_EVERY, clock)
        self.last_sent_wall = 0.0   # wall clock, to compare with the tv-off marker
        self.marker = marker
        self.away = away

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
        if self.away():
            return   # the press that switched the TV to another input: don't switch it back
        if not self.activity.ready() and not self._tv_turned_off_since_last_send():
            return
        self.activity.touch()
        self.last_sent_wall = time.time()
        self._send("gamepad_activity", self._name(event.device))

    def wake(self, event):
        """A press while the TV is off: always sent, whatever the once-a-minute limit."""
        self.activity.touch()
        self.last_sent_wall = time.time()
        self._send("gamepad_activity", self._name(event.device))

    def tick(self):
        now = Counter(self.gamepads.connected())
        if self.pads is not None:
            for name in (now - self.pads).elements():
                self.activity.touch()  # this already says "someone is here"
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
    """"on", "off", "away" (on, but showing another input than the HTPC's), or
    None when unknown (not set up, unavailable, unreachable)."""
    if not api_ready(cfg):
        return None
    data = _api(cfg, "states/" + cfg["home_assistant"]["tv_entity"], get)
    state = data.get("state")
    if state in OFF_STATES:
        return "off"
    if state in ("unavailable", "unknown", None):
        return None
    home = cfg["home_assistant"].get("htpc_source")
    source = (data.get("attributes") or {}).get("source")
    if home and source and source != home:
        return "away"
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


def is_press(event, dead_zone=STICK_DEAD_ZONE):
    if event.kind == "button":
        return bool(event.value)
    if event.kind == "axis":
        return abs(event.value) > dead_zone
    return False


class TvGate:
    """In the controller service: keeps the TV's state and swallows input while it is off."""

    def __init__(self, settings, send_wake, get=None, clock=time.monotonic, gate=write_gate,
                 away=recently_away):
        self.settings = settings
        self.send_wake = send_wake      # called with the event that should wake the TV
        self.get = get
        self.clock = clock
        self.gate = gate
        self.state = None               # "on" / "off" / None
        self.last_wake = None
        self.wakes = []                 # times of the recent wake requests
        self.distrust_until = None      # Home Assistant says "off" but the TV doesn't wake up
        self.gate_written = None        # what the gate file says now (None: not written yet)
        self.away = away
        self._lock = threading.Lock()

    def _set_gate(self, blocked):
        """Write the gate file when it changes, and keep a closed one fresh (the
        launcher ignores a gate older than GATE_FRESH). An open gate is written
        once: rewriting it every few seconds, all day, would only wear the disk."""
        if blocked or self.gate_written is not False:
            self.gate(blocked)
            self.gate_written = bool(blocked)

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
            if state not in ("off", "away"):
                self.last_wake = None
                self.wakes = []
                self.distrust_until = None
            blocked = state in ("off", "away") and not self._distrusted()
        self._set_gate(blocked)

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
            if self.state not in ("off", "away") or self._distrusted():
                return False
            if not is_press(event):
                return False   # releases and a stick going back to the middle are harmless
            if self.state == "away" and self.away():
                return True    # just switched away by the launcher: not this press
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
            self._set_gate(False)
            return False
        if wake:
            log.info("tv is %s: this press only brings it back",
                     "off" if self.state == "off" else "on another input")
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
        self.every = Throttle(EVENTS_EVERY, clock)

    def tick(self):
        if not self.every.ready():
            return
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
                running.add(app.get("name") or app.get("id", "?"))
                if w.focused:
                    front = app.get("name") or app.get("id", "?")
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


# --- the home screen's "Home" row: lights and switches --------------------------------
#
# With the address and the token, the launcher lists lights and switches under
# the apps and turns them on and off. Which ones: "devices" (entity ids, in
# that order) in the "home_assistant" entry, chosen in Settings → Home
# Assistant → Devices; without it, every light. Scenes: "scenes", likewise;
# without it, every scene. "home_screen": false hides the row;
# "group_by_area": true shows them under their rooms' names (in the order the
# rooms first come in "devices"); "names": {entity: name} shows names of your
# own instead of Home Assistant's.

DEVICE_DOMAINS = ("light", "switch", "fan", "input_boolean")
SCENE_DOMAINS = ("scene", "script")
DEFAULT_SCENES = 6


def home_ready(cfg):
    """Can the home screen show the house? (enabled, address and token set)"""
    ha = (cfg or {}).get("home_assistant") or {}
    return bool(ha.get("enabled", True) and ha.get("home_screen", True) and ha.get("url") and ha.get("token"))


def http_post_api(url, token, payload):
    """POST to the REST API with the token; the reply's text."""
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": f"htpc-launcher/{__version__}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def _post(cfg, path, payload, post=None):
    ha = cfg["home_assistant"]
    return (post or http_post_api)(f"{ha['url'].rstrip('/')}/api/{path}", ha["token"], payload)


# media_player supported_features bits
VOLUME_SET, VOLUME_MUTE, VOLUME_STEP = 4, 8, 1024
TV_VOLUME_STEP = 0.02     # 2 of the TV's 100 steps per press


def volume_target(cfg):
    """"tv" when the volume shortcut goes to the TV through Home Assistant
    (Settings → Home Assistant → Volume), else "computer"."""
    ha = (cfg or {}).get("home_assistant") or {}
    return "tv" if api_ready(cfg) and ha.get("volume") == "tv" else "computer"


def tv_volume_support(cfg, get=None):
    """Can Home Assistant change this TV's volume? (reads the TV's state)"""
    data = _api(cfg, "states/" + cfg["home_assistant"]["tv_entity"], get)
    features = int((data.get("attributes") or {}).get("supported_features") or 0)
    return bool(features & (VOLUME_SET | VOLUME_STEP))


def change_tv_volume(cfg, direction, get=None, post=None):
    """One step up (+1) or down (-1) on the TV. (level 0..1, muted), or None when
    the TV doesn't say its level. Raises on network errors."""
    entity = cfg["home_assistant"]["tv_entity"]
    data = _api(cfg, "states/" + entity, get)
    attrs = data.get("attributes") or {}
    features = int(attrs.get("supported_features") or 0)
    level, muted = attrs.get("volume_level"), bool(attrs.get("is_volume_muted"))
    if features & VOLUME_SET and level is not None:
        level = max(0.0, min(1.0, round(float(level) + direction * TV_VOLUME_STEP, 2)))
        _post(cfg, "services/media_player/volume_set", {"entity_id": entity, "volume_level": level}, post)
        return level, muted
    if features & VOLUME_STEP:
        _post(cfg, "services/media_player/" + ("volume_up" if direction > 0 else "volume_down"),
              {"entity_id": entity}, post)
        if level is None:
            return None
        # One step is one of the TV's 100 (LG webOS); its state catches up a moment later.
        return max(0.0, min(1.0, round(float(level) + direction * 0.01, 2))), muted
    raise ValueError(f"{entity} can't change its volume through Home Assistant")


def wake_on_lan(cfg, target, post=None):
    """Wakes a computer before an app that needs it (a game-streaming PC for Steam).
    target: an automation or script of yours that turns it on (automation.trigger,
    script.turn_on), a Wake-on-LAN button (button.press) or a MAC address
    (wake_on_lan.send_magic_packet)."""
    target = target.strip()
    if target.startswith("automation."):
        _post(cfg, "services/automation/trigger", {"entity_id": target}, post)
    elif target.startswith("script."):
        _post(cfg, "services/script/turn_on", {"entity_id": target}, post)
    elif target.startswith("button."):
        _post(cfg, "services/button/press", {"entity_id": target}, post)
    elif re.fullmatch(r"[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}", target):
        _post(cfg, "services/wake_on_lan/send_magic_packet", {"mac": target.replace("-", ":")}, post)
    else:
        raise ValueError(f"not a Wake-on-LAN button or MAC address: {target}")


def _domain(entity):
    return entity.split(".", 1)[0]


def _name(state):
    return (state.get("attributes") or {}).get("friendly_name") or state.get("entity_id", "?")


def areas(cfg, entities, post=None):
    """{entity: area name or None}, in one template call. {} if that fails
    (an old Home Assistant, or a token without access to templates)."""
    if not entities:
        return {}
    pairs = ", ".join(f"{json.dumps(e)}: area_name({json.dumps(e)})" for e in entities)
    try:
        found = json.loads(_post(cfg, "template", {"template": "{{ {" + pairs + "} | tojson }}"}, post))
    except Exception as e:  # noqa: BLE001 - without areas the cards just don't say the room
        log.debug("Home Assistant areas: %s", e)
        return {}
    return found if isinstance(found, dict) else {}


COLOR_MODES = {"hs", "rgb", "rgbw", "rgbww", "xy"}


def _device(state, area):
    entity = state["entity_id"]
    attrs = state.get("attributes") or {}
    brightness = attrs.get("brightness")
    modes = set(attrs.get("supported_color_modes") or [])
    light = _domain(entity) == "light"
    hs = attrs.get("hs_color")
    return {
        "entity": entity,
        "domain": _domain(entity),
        "name": _name(state),
        "area": area,
        "state": state.get("state"),
        "on": state.get("state") == "on",
        "available": state.get("state") not in ("unavailable", "unknown", None),
        "brightness": round(brightness / 2.55) if isinstance(brightness, (int, float)) and state.get("state") == "on" else None,
        "dimmable": light and any(m != "onoff" for m in modes),
        "color": light and bool(modes & COLOR_MODES),
        "temperature": light and "color_temp" in modes,
        "min_kelvin": int(attrs.get("min_color_temp_kelvin") or 2000),
        "max_kelvin": int(attrs.get("max_color_temp_kelvin") or 6500),
        "kelvin": attrs.get("color_temp_kelvin") if state.get("state") == "on" else None,
        "hs": list(hs) if isinstance(hs, (list, tuple)) and len(hs) == 2 and attrs.get("color_mode") in COLOR_MODES
        else None,
    }


def device_candidates(cfg, get=None):
    """[(entity, name)] of every light and switch, for Settings → Devices."""
    found = [(s["entity_id"], _name(s)) for s in _api(cfg, "states", get)
             if _domain(str(s.get("entity_id", ""))) in DEVICE_DOMAINS]
    return sorted(found, key=lambda item: (_domain(item[0]) != "light", item[1].lower()))


def house(cfg, get=None, post=None):
    """{"devices": [...], "scenes": [...]} for the home screen's Home row."""
    ha = cfg["home_assistant"]
    states = {s.get("entity_id"): s for s in _api(cfg, "states", get) if s.get("entity_id")}
    chosen = ha.get("devices")
    if isinstance(chosen, list):
        ids = [e for e in chosen if e in states]
    else:
        ids = [e for e in states if _domain(e) == "light"]
    found = areas(cfg, ids, post)
    names = ha.get("names") if isinstance(ha.get("names"), dict) else {}
    devices = [_device(states[e], found.get(e)) for e in ids]
    for d in devices:   # a name of your own, like a dashboard card's
        if names.get(d["entity"]):
            d["name"] = str(names[d["entity"]])
    if not isinstance(chosen, list):   # no choice made: by room, then name
        devices.sort(key=lambda d: ((d["area"] or "￿").lower(), d["name"].lower()))
    elif ha.get("group_by_area"):     # grouped: rooms in the order they first come in the choice
        first = {}
        for d in devices:
            first.setdefault(d["area"], len(first))
        devices.sort(key=lambda d: first[d["area"]] if d["area"] else len(first))
    scene_ids = ha.get("scenes")
    if isinstance(scene_ids, list):
        scene_ids = [e for e in scene_ids if e in states]
    else:
        scene_ids = sorted((e for e in states if _domain(e) == "scene"),
                           key=lambda e: _name(states[e]).lower())[:DEFAULT_SCENES]
    scenes = [{"entity": e, "name": _name(states[e])} for e in scene_ids]
    return {"devices": devices, "scenes": scenes}


def toggle(cfg, entity, post=None):
    """Turn a light or switch on/off, or run a scene or script."""
    domain = _domain(entity)
    service = "turn_on" if domain in SCENE_DOMAINS else "toggle"
    _post(cfg, f"services/{domain}/{service}", {"entity_id": entity}, post)


def set_light(cfg, entity, post=None, **values):
    """Turn a light on with any of brightness_pct, color_temp_kelvin, hs_color."""
    _post(cfg, "services/light/turn_on", {"entity_id": entity, **values}, post)


def set_brightness(cfg, entity, percent, post=None):
    """A light's brightness, 1-100 % (0 turns it off)."""
    if percent <= 0:
        _post(cfg, "services/light/turn_off", {"entity_id": entity}, post)
    else:
        _post(cfg, "services/light/turn_on", {"entity_id": entity, "brightness_pct": min(100, int(percent))}, post)
