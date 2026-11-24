# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""On-screen notices shown over whatever is playing.

The controller service calls Notifier.tick() every couple of seconds. It
compares what it sees with the last time and asks the window control (the
GNOME extension on Linux) to show a short notice when:

  * a gamepad connects or disconnects;
  * a wireless gamepad's battery gets low (20 %) and again when it is almost
    empty (10 %), once per connection, until it charges;
  * the internet goes down or becomes limited, and when it comes back.

Nothing is announced for what was already there when the service started, and
the internet has to stay in a new state for a few seconds before it counts,
so a short blip does not show anything. Turned off with "notifications": false
in apps.json (Settings has a switch).
"""

import logging
import time
from collections import Counter

from . import config, paths
from .i18n import Translator

log = logging.getLogger("htpc-controller")

LOW, CRITICAL = 20, 10       # battery percentages
INTERNET_SETTLE = 8.0        # seconds a new internet state must last
SHOW_FOR = 6                 # seconds a notice stays on screen


def _battery_stage(b):
    """0 fine, 1 low, 2 almost empty (from the percentage or the level)."""
    if b.charging:
        return 0
    if b.percent is not None:
        return 2 if b.percent <= CRITICAL else 1 if b.percent <= LOW else 0
    return {"critical": 2, "low": 1}.get(b.level, 0)


class Notifier:
    def __init__(self, backend, gamepads=None, clock=time.monotonic, settings=None):
        # The reader the service polls: a reader nobody polls never sees a gamepad.
        self.gamepads = gamepads or backend.gamepads()
        self.system = backend.system()
        self.backend = backend
        self._windows = None
        self.clock = clock
        self.settings = settings or (lambda: config.load()[0])
        self.pads = None             # Counter of gamepad names, None until the first look
        self.battery_stage = {}      # gamepad name -> last stage announced
        self.internet = None         # last announced state: "full", "limited", "none"
        self.pending = None          # (state, since)

    @property
    def windows(self):
        if self._windows is None:
            self._windows = self.backend.window_control()
        return self._windows

    # --- showing -----------------------------------------------------------------

    def _show(self, title, body, icon):
        try:
            cfg = self.settings()
        except Exception:  # noqa: BLE001 - a broken apps.json must not stop the service
            cfg = {}
        if cfg.get("notifications", True) is False:
            return
        t = Translator(cfg.get("language", "en"))
        title, body = t(title), body if isinstance(body, str) else t(*body[:1], **body[1])
        log.info("notice: %s - %s", title, body)
        try:
            self.windows.notify(title, body, str(paths.data_dir() / "icons" / icon), SHOW_FOR)
        except Exception as e:  # noqa: BLE001
            log.warning("could not show a notice: %s", e)

    # --- checks --------------------------------------------------------------------

    def tick(self):
        self._check_pads()
        self._check_batteries()
        self._check_internet()

    def _check_pads(self):
        now = Counter(self.gamepads.connected())
        if self.pads is None:  # first look: what is already there is not news
            self.pads = now
            return
        for name in (now - self.pads).elements():
            self._show("notify_pad_connected", name, "gamepad.svg")
        for name in (self.pads - now).elements():
            self._show("notify_pad_disconnected", name, "gamepad-off.svg")
            self.battery_stage.pop(name, None)
        self.pads = now

    def _check_batteries(self):
        for b in self.gamepads.batteries():
            stage = _battery_stage(b)
            before = self.battery_stage.get(b.name, 0)
            self.battery_stage[b.name] = stage
            if stage > before:
                key = "notify_battery_empty" if stage == 2 else "notify_battery_low"
                body = ("notify_battery_body", {"name": b.name, "percent": b.percent}) \
                    if b.percent is not None else b.name
                self._show(key, body, f"battery-{0 if stage == 2 else 1}.svg")

    def _check_internet(self):
        state = self.system.connectivity()
        if state is None:
            return  # the OS cannot tell
        if self.internet is None:
            self.internet = state  # what it was when the service started
            return
        if state == self.internet:
            self.pending = None
            return
        now = self.clock()
        if self.pending is None or self.pending[0] != state:
            self.pending = (state, now)
            return
        if now - self.pending[1] < INTERNET_SETTLE:
            return
        before, self.internet, self.pending = self.internet, state, None
        kind = self.system.connection_kind() or "wifi"
        if state == "full":
            self._show("notify_internet_back", "", f"{kind}.svg")
        elif state == "limited":
            self._show("notify_internet_limited", "", f"{kind}-limited.svg")
        elif before != "none":
            self._show("notify_internet_down", "", f"{kind}-off.svg")
