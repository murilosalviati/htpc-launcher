# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Controller service tests against a fake GNOME extension and MPRIS player.

Run: dbus-run-session -- python3 tests/test_controller.py
"""
import json
import logging
import os
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "controller"))
sys.path.insert(0, os.path.dirname(__file__))

# Start from a config in the OLD (Portuguese) format, to check that it still works.
cfgdir = tempfile.mkdtemp()
os.makedirs(f"{cfgdir}/htpc-launcher")
cfg = json.load(open(os.path.join(ROOT, "config", "apps.json")))
legacy = {"name": "nome", "launch": "abrir", "icon": "icone", "extra_ids": "outros_ids", "close": "fechar",
          "close_timeout": "espera_fechar", "pause_on_home": "pausar_ao_sair",
          "close_on_second_press": "fechar_em_dois_toques", "preferred_windows": "janelas_preferidas"}
cfg.pop("language")
cfg["apps"] = [{legacy.get(k, k): v for k, v in a.items()} for a in cfg["apps"]]
json.dump(cfg, open(f"{cfgdir}/htpc-launcher/apps.json", "w"))
os.environ["XDG_CONFIG_HOME"] = cfgdir

import controller  # noqa: E402
import fakes  # noqa: E402
from evdev import ecodes  # noqa: E402

logging.basicConfig(level="INFO", format="  [log] %(message)s")
controller.MIN_INTERVAL = 0.3
controller.DEFAULT_CLOSE_TIMEOUT = 1.0
killed = []
controller.force_close = lambda app, pid: killed.append(app) or [fakes.state["windows"].remove(w) for w in fakes.find(app)]

fakes.start()
time.sleep(0.5)

pads = controller.Gamepads(controller.Actions())
pads.pressed["pad"] = set()


def press(*buttons):
    for b in buttons:
        pads.handle("pad", SimpleNamespace(type=ecodes.EV_KEY, code=b, value=1))
    for b in buttons:
        pads.handle("pad", SimpleNamespace(type=ecodes.EV_KEY, code=b, value=0))


COMBO = (ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL, ecodes.BTN_TR)
S = fakes.state


def running():
    return [w["appId"] for w in S["windows"]]


ok = True


def check(name, cond):
    global ok
    print(("OK     " if cond else "FAILED ") + name)
    ok &= bool(cond)


# 0. the old config format is read as the new one
cfg_loaded = controller.load_config()
check("old Portuguese apps.json is translated on load",
      cfg_loaded["apps"][0]["name"] == "YouTube" and cfg_loaded["apps"][0]["pause_on_home"] is True
      and cfg_loaded["language"] == "pt-BR")

# 1. guide on Jellyfin while it plays: pauses, shows the launcher, Jellyfin stays open
press(ecodes.BTN_MODE); time.sleep(0.2)
check("guide pauses the video", S["player"] == "Paused")
check("guide shows the launcher", S["focus"] == "htpc-launcher")
check("Jellyfin stays open", "org.jellyfin.JellyfinDesktop" in running())

# 2. the repeat from Steam's virtual gamepad is ignored
n = len(S["log"]); press(ecodes.BTN_MODE); time.sleep(0.1)
check("a guide repeated right away is ignored", len(S["log"]) == n)
time.sleep(0.4)

# 3. combo with the launcher focused does nothing
press(*COMBO); time.sleep(0.3)
check("combo on the launcher closes nothing", len(running()) == 5)
time.sleep(0.4)

# 4. combo on YouTube closes it and returns to the launcher
S["focus"] = "rocks.shy.VacuumTube"
press(*COMBO); time.sleep(0.8)
check("combo closes YouTube", "rocks.shy.VacuumTube" not in running())
check("after closing, the launcher is in front", S["focus"] == "htpc-launcher")

# 5. Moonlight: first press does not close, second does
S["focus"] = "com.moonlight_stream.Moonlight"; time.sleep(0.4)
press(*COMBO); time.sleep(0.5)
check("first press on Moonlight does not close it", "com.moonlight_stream.Moonlight" in running())
S["focus"] = "com.moonlight_stream.Moonlight"
press(*COMBO); time.sleep(0.8)
check("second press closes Moonlight", "com.moonlight_stream.Moonlight" not in running())

# 6. stubborn app: forced to close after the timeout
S["focus"] = "game"; time.sleep(0.4)
press(*COMBO); time.sleep(1.8)
check("an app that does not close is forced", killed == ["game"] and "game" not in running())

# 7. only three of the combo buttons do not close
S["focus"] = "org.jellyfin.JellyfinDesktop"; time.sleep(0.4)
press(ecodes.BTN_START, ecodes.BTN_SELECT, ecodes.BTN_TL); time.sleep(0.4)
check("incomplete combo does not close", "org.jellyfin.JellyfinDesktop" in running())

# 8. service without the graphical session's variables: only missing ones are filled
for v in ("DISPLAY", "WAYLAND_DISPLAY"):
    os.environ.pop(v, None)
os.environ["XDG_RUNTIME_DIR"] = "/run/user/1234"
env = controller.graphical_env()
check("fills in missing DISPLAY and WAYLAND_DISPLAY", env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-0")
os.environ["DISPLAY"] = ":1"
check("keeps a DISPLAY that already exists", controller.graphical_env()["DISPLAY"] == ":1")

print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
