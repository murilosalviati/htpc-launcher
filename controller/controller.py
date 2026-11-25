#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""HTPC controller service.

Reads every connected gamepad without taking the buttons away from the apps,
and runs the shortcuts from htpc.shortcuts:

  * Guide (Xbox / Home / PS): pause the video and show the launcher;
  * Start + Select + L1 + R1: close the focused app.

It also shows on-screen notices (htpc.notifications) when a gamepad connects,
disconnects or runs low on battery, and when the internet drops or comes back,
and tells Home Assistant when the gamepad is used (htpc.home_assistant), so an
automation there can turn the TV on and pick the right input.

Everything OS-specific (reading gamepads, finding and closing windows, pausing
media) comes from the backend for the running OS (htpc.backends).
"""

import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Installed: the htpc package sits next to this file. In the repo: one folder up.
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))

from htpc import config  # noqa: E402
from htpc.backends import get_backend  # noqa: E402
from htpc.home_assistant import AppEvents, HomeAssistant, TvGate  # noqa: E402
from htpc.notifications import Notifier  # noqa: E402
from htpc.shortcuts import GamepadShortcuts, Shortcuts  # noqa: E402

log = logging.getLogger("htpc-controller")


def run(backend, poll_timeout=2.0):
    gamepads = backend.gamepads()
    if not gamepads.available():
        raise SystemExit("This backend cannot read gamepads here (is python3-evdev installed?)")
    handler = GamepadShortcuts(Shortcuts(backend))
    notifier = Notifier(backend, gamepads)
    home_assistant = HomeAssistant(gamepads)
    tv = TvGate(home_assistant.settings, home_assistant.wake)
    tv.start()
    events = AppEvents(backend.window_control(), backend.media(), home_assistant.settings)
    while True:
        for event in gamepads.poll(handler.timeout(poll_timeout)):
            if event.kind == "disconnected":
                handler.forget(event.device)
            elif tv.blocks(event):
                continue   # the TV is off: this press only woke it
            else:
                handler.handle(event)
                home_assistant.button(event)
        handler.tick()   # holding a volume combo keeps changing it
        for job in (notifier.tick, home_assistant.tick, events.tick):
            try:
                job()
            except Exception as e:  # noqa: BLE001 - extras must never stop the shortcuts
                log.warning("%s: %s", job.__qualname__, e)


def main():
    logging.basicConfig(level=os.environ.get("HTPC_LOG", "INFO"),
                        format="%(levelname)s %(message)s")
    if not config.exists():
        raise SystemExit("Missing configuration file (apps.json); run the installer first.")
    run(get_backend())


if __name__ == "__main__":
    main()
