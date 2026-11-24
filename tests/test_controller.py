# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Shortcut and Linux backend tests against a fake GNOME extension and MPRIS player.

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
sys.path.insert(0, ROOT)
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

import fakes  # noqa: E402
from htpc import config, shortcuts  # noqa: E402
from htpc.backends import get_backend  # noqa: E402
from htpc.backends.base import Backend, GamepadEvent  # noqa: E402
from htpc.backends.linux import system as linux_system  # noqa: E402
from htpc.backends.linux.gamepads import EvdevGamepads  # noqa: E402
from evdev import ecodes  # noqa: E402

logging.basicConfig(level="INFO", format="  [log] %(message)s")
shortcuts.MIN_INTERVAL = 0.3
shortcuts.DEFAULT_CLOSE_TIMEOUT = 1.0
killed = []
linux_system.LinuxSystem.force_close = lambda self, app, pid: killed.append(app) or [fakes.state["windows"].remove(w) for w in fakes.find(app)]

fakes.start()
time.sleep(0.5)

ok = True


def check(name, cond):
    global ok
    print(("OK     " if cond else "FAILED ") + name)
    ok &= bool(cond)


backend = get_backend()
check("Linux picks the Linux backend", backend.name == "linux" and isinstance(backend, Backend))

handler = shortcuts.GamepadShortcuts(shortcuts.Shortcuts(backend))


def press(*buttons):
    for b in buttons:
        handler.handle(GamepadEvent("pad", "button", b, 1))
    for b in buttons:
        handler.handle(GamepadEvent("pad", "button", b, 0))


COMBO = ("start", "select", "l1", "r1")
S = fakes.state


def running():
    return [w["appId"] for w in S["windows"]]


# 0. the old config format is read as the new one
cfg_loaded = config.load()[0]
check("old Portuguese apps.json is translated on load",
      cfg_loaded["apps"][0]["name"] == "YouTube" and cfg_loaded["apps"][0]["pause_on_home"] is True
      and cfg_loaded["language"] == "pt-BR")

# 1. guide on Jellyfin while it plays: pauses, shows the launcher, Jellyfin stays open
press("guide"); time.sleep(0.2)
check("guide pauses the video", S["player"] == "Paused")
check("guide shows the launcher", S["focus"] == "htpc-launcher")
check("Jellyfin stays open", "org.jellyfin.JellyfinDesktop" in running())

# 2. the repeat from Steam's virtual gamepad is ignored
n = len(S["log"]); press("guide"); time.sleep(0.1)
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
press("start", "select", "l1"); time.sleep(0.4)
check("incomplete combo does not close", "org.jellyfin.JellyfinDesktop" in running())

# 8. service without the graphical session's variables: only missing ones are filled
for v in ("DISPLAY", "WAYLAND_DISPLAY"):
    os.environ.pop(v, None)
os.environ["XDG_RUNTIME_DIR"] = "/run/user/1234"
env = linux_system.graphical_env()
check("fills in missing DISPLAY and WAYLAND_DISPLAY", env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-0")
os.environ["DISPLAY"] = ":1"
check("keeps a DISPLAY that already exists", linux_system.graphical_env()["DISPLAY"] == ":1")

# 9. evdev events become normalized gamepad events
pads = EvdevGamepads()
dev = SimpleNamespace(absinfo=lambda code: SimpleNamespace(min=-32768, max=32767))


def raw(type_, code, value):
    return SimpleNamespace(type=type_, code=code, value=value)


ev = pads.translate("p", dev, raw(ecodes.EV_KEY, ecodes.BTN_MODE, 1))
check("evdev: BTN_MODE becomes 'guide'", [(e.kind, e.name, e.value) for e in ev] == [("button", "guide", 1)])
ev = pads.translate("p", dev, raw(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1)) + \
    pads.translate("p", dev, raw(ecodes.EV_ABS, ecodes.ABS_HAT0X, -1))
check("evdev: the d-pad hat becomes right press, right release, left press",
      [(e.name, e.value) for e in ev] == [("right", 1), ("right", 0), ("left", 1)])
ev = pads.translate("p", dev, raw(ecodes.EV_ABS, ecodes.ABS_X, 32767))
check("evdev: the left stick becomes a -1..1 axis", ev[0].name == "lx" and abs(ev[0].value - 1.0) < 0.01)

# 9b. counting connected gamepads: one per physical gamepad, virtual ones left out
pads = EvdevGamepads()
pads.devs = {
    "/dev/input/event5": SimpleNamespace(name="Xbox Wireless Controller", uniq="aa:bb"),
    "/dev/input/event6": SimpleNamespace(name="8BitDo Pro 2", uniq=""),
    "/dev/input/event7": SimpleNamespace(name="Xbox Wireless Controller", uniq="aa:bb"),
    "/dev/input/event9": SimpleNamespace(name="Microsoft X-Box 360 pad 0", uniq=""),
}
pads.virtual = {"/dev/input/event9": True}
check("gamepads: counts each physical gamepad once and skips virtual ones",
      pads.connected() == ["Xbox Wireless Controller", "8BitDo Pro 2"])
pads.devs = {}
check("gamepads: none connected", pads.connected() == [])

# 9c. weather: finding the place and reading the conditions (no network: a fake fetch)
from htpc import weather  # noqa: E402

GEO = {"results": [
    {"name": "Araranguá", "latitude": -28.9, "longitude": -49.5, "country_code": "BR", "admin1": "Santa Catarina"},
    {"name": "Campinas", "latitude": -3.7, "longitude": -39.7, "country_code": "BR", "admin1": "Ceará"},
    {"name": "Campinas", "latitude": -22.9, "longitude": -47.0, "country_code": "BR", "admin1": "São Paulo"},
]}


def fetch(url):
    if "viacep" in url:
        return {"erro": "true"} if "00000000" in url else {"localidade": "Campinas", "uf": "SP"}
    if "geocoding" in url:
        if "Lisbon" in url:
            return {"results": [{"name": "Lisbon", "latitude": 38.7, "longitude": -9.1,
                                 "country_code": "PT", "admin1": "Lisbon"}]}
        return GEO if "Campinas" in url else {"generationtime_ms": 0.1}
    return {"current": {"temperature_2m": 18.6, "weather_code": 61, "is_day": 0}}


check("weather: CEP with or without dash and dots", weather.cep_digits("13.010-001") == "13010001"
      and weather.cep_digits("Campinas") is None)
p = weather.find_place("13010-001", "pt-BR", fetch)
check("weather: a CEP picks the town in its own state", (p.name, p.latitude) == ("Campinas, SP", -22.9))
p = weather.find_place("Lisbon", "en", fetch)
check("weather: a city name outside Brazil", p.name == "Lisbon, Lisbon" and p.longitude == -9.1)
for bad in ("00000-000", "Nowhere", ""):
    try:
        weather.find_place(bad, "en", fetch)
        check(f"weather: {bad!r} is not found", False)
    except weather.NotFound:
        check(f"weather: {bad!r} is not found", True)
c = weather.current(-22.9, -47.0, "celsius", fetch)
check("weather: rain at night, rounded", (c.temperature, c.kind, c.icon) == (19, "rain", "weather-rain.svg"))
check("weather: codes map to icons",
      [weather.kind_for_code(x) for x in (0, 2, 3, 45, 63, 81, 75, 95)]
      == ["clear", "partly", "cloudy", "fog", "rain", "rain", "snow", "storm"])
check("weather: clear at night is the moon",
      weather.Conditions(10, "clear", False).icon == "weather-clear-night.svg")

# 10. the Windows backend is a documented placeholder for now
from htpc.backends.windows import WindowsBackend  # noqa: E402
try:
    WindowsBackend().window_control()
    check("Windows backend says what is missing", False)
except NotImplementedError as e:
    check("Windows backend says what is missing", "window control" in str(e))

print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
