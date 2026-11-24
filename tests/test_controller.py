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

# 8. started without the graphical session's variables (systemd service, SSH):
#    missing ones come from the session, then from defaults
for v in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY"):
    os.environ.pop(v, None)
runtime = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = runtime
real_session_env = linux_system.session_env
linux_system.session_env = lambda: {}
open(f"{runtime}/.mutter-Xwaylandauth.ABC123", "w").close()
env = linux_system.graphical_env()
check("no session info: fills DISPLAY, WAYLAND_DISPLAY and Xwayland's XAUTHORITY",
      env["DISPLAY"] == ":0" and env["WAYLAND_DISPLAY"] == "wayland-0"
      and env["XAUTHORITY"] == f"{runtime}/.mutter-Xwaylandauth.ABC123")
linux_system.session_env = lambda: {"DISPLAY": ":1", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.XYZ"}
env = linux_system.graphical_env()
check("takes DISPLAY and XAUTHORITY from the session", env["DISPLAY"] == ":1" and env["XAUTHORITY"].endswith("XYZ"))
os.environ["DISPLAY"] = ":5"
check("keeps a DISPLAY that already exists", linux_system.graphical_env()["DISPLAY"] == ":5")
linux_system.session_env = real_session_env


class FakeRun:
    stdout = "HOME=/home/u\nDISPLAY=:0\nXAUTHORITY=$'/run/user/1000/.mutter-Xwaylandauth.Q1'\nLANG=pt_BR.UTF-8\n"


real_run = linux_system.subprocess.run
linux_system.subprocess.run = lambda *a, **k: FakeRun()
check("reads systemd's environment, only the session variables",
      linux_system.session_env() == {"DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.Q1"})
linux_system.subprocess.run = real_run

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

# 9a1. using the gamepad hides the mouse pointer, at most once every few seconds
from htpc import shortcuts as sc  # noqa: E402
hidden = []
stub = SimpleNamespace(windows=SimpleNamespace(hide_pointer=lambda: hidden.append(1)),
                       guide=lambda: None, close=lambda: None)
gs = sc.GamepadShortcuts(stub)
from htpc.backends.base import GamepadEvent  # noqa: E402
for _ in range(5):
    gs.handle(GamepadEvent("p", "button", "a", 1))
    gs.handle(GamepadEvent("p", "button", "a", 0))
check("gamepad use hides the pointer once, not on every press", hidden == [1])
gs.pointer_hidden_at -= sc.POINTER_EVERY
gs.handle(GamepadEvent("p", "button", "down", 1))
check("and again after a while (the mouse may have shown it)", hidden == [1, 1])

# 9a2. X and Y by gamepad: Xbox-style drivers send them swapped by position
from htpc.backends.linux import gamepads as lg  # noqa: E402
pads = EvdevGamepads()
pads.xbox_codes = {"xbox": True, "ps4": False}
xb = [pads.translate("xbox", dev, raw(ecodes.EV_KEY, code, 1))[0].name
      for code in (ecodes.BTN_X, ecodes.BTN_Y, ecodes.BTN_SOUTH, ecodes.BTN_EAST)]
check("Xbox pad: X is X, Y is Y, A and B unchanged", xb == ["x", "y", "a", "b"])
ps = [pads.translate("ps4", dev, raw(ecodes.EV_KEY, code, 1))[0].name
      for code in (ecodes.BTN_WEST, ecodes.BTN_NORTH)]
check("PS4/Nintendo pad (positional codes): square/left is X, triangle/top is Y", ps == ["x", "y"])
check("Xbox codes detected by name, not for other pads",
      lg.uses_xbox_codes("/dev/input/event999", "Microsoft Xbox Series S|X Controller")
      and lg.uses_xbox_codes("/dev/input/event999", "Microsoft X-Box 360 pad 0")
      and not lg.uses_xbox_codes("/dev/input/event999", "Wireless Controller"))

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

# 9b2. gamepad batteries: matched to the gamepad by sysfs path
import os as _os  # noqa: E402
ps = tempfile.mkdtemp()
dev_root = tempfile.mkdtemp()
hid = _os.path.join(dev_root, "0005:045E:0B13.0001")
_os.makedirs(_os.path.join(hid, "input", "input40"))
mouse = _os.path.join(dev_root, "mouse")
_os.makedirs(mouse)


def supply(name, device, **files):
    d = _os.path.join(ps, name)
    _os.makedirs(d)
    _os.symlink(device, _os.path.join(d, "device"))
    for k, v in files.items():
        open(_os.path.join(d, k), "w").write(v + "\n")


supply("hid-aa-battery", hid, type="Battery", scope="Device", capacity="42", status="Discharging")
supply("hid-mouse-battery", mouse, type="Battery", scope="Device", capacity_level="Low", status="Discharging")
supply("BAT0", dev_root, type="Battery", scope="System", capacity="90")
pads = EvdevGamepads()
pads.devs = {"/dev/input/event40": SimpleNamespace(name="Xbox Wireless Controller", uniq="aa"),
             "/dev/input/event41": SimpleNamespace(name="Wired pad", uniq="")}
pads.sysfs = {"/dev/input/event40": _os.path.join(hid, "input", "input40"),
              "/dev/input/event41": _os.path.join(dev_root, "usb", "input41")}
pads.virtual = {}
bats = pads.batteries(ps)
check("battery: the wireless pad's battery is found through its parent device, the wired one has none",
      [(b.name, b.percent, b.bars) for b in bats] == [("Xbox Wireless Controller", 42, 2)])
from htpc.backends.base import Battery  # noqa: E402
check("battery: levels without a percentage still map to bars",
      [Battery("x", level=l).bars for l in ("full", "high", "normal", "low", "critical")] == [4, 3, 2, 1, 0])

# 9b2b. one gamepad reader per backend: its list only updates through poll()
from htpc.backends.linux import LinuxBackend  # noqa: E402
lb = LinuxBackend()
check("the Linux backend hands out the same gamepad reader every time", lb.gamepads() is lb.gamepads())

# 9b3. on-screen notices: gamepads, batteries and internet
from htpc import notifications as nt  # noqa: E402


class FakeBackend:
    def __init__(self):
        self.pads, self.bats, self.net, self.kind, self.shown = [], [], "full", "wired", []
        outer = self
        self._g = SimpleNamespace(connected=lambda: list(outer.pads), batteries=lambda: list(outer.bats))
        self._s = SimpleNamespace(connectivity=lambda: outer.net, connection_kind=lambda: outer.kind)
        self._w = SimpleNamespace(notify=lambda t, b, i, s: outer.shown.append((t, b, i.rsplit("/", 1)[-1])))

    def gamepads(self): return self._g
    def system(self): return self._s
    def window_control(self): return self._w


clock = [100.0]
fb = FakeBackend()
fb.pads = ["Xbox Series"]
lang = {"language": "pt-BR"}
n = nt.Notifier(fb, clock=lambda: clock[0], settings=lambda: lang)
n.tick()
check("notices: nothing for what was already there at start", fb.shown == [])
fb.pads = ["Xbox Series", "8BitDo Pro 2"]
n.tick()
check("notices: a gamepad connecting", fb.shown[-1] == ("Controle conectado", "8BitDo Pro 2", "gamepad.svg"))
fb.pads = ["Xbox Series"]
n.tick()
check("notices: a gamepad disconnecting", fb.shown[-1] == ("Controle desconectado", "8BitDo Pro 2", "gamepad-off.svg"))
count = len(fb.shown)
fb.bats = [Battery("Xbox Series", 35)]
n.tick()
fb.bats = [Battery("Xbox Series", 19)]
n.tick()
n.tick()
check("notices: battery low once, with the percentage",
      fb.shown[count:] == [("Bateria do controle fraca", "Xbox Series: 19%", "battery-1.svg")])
fb.bats = [Battery("Xbox Series", 9)]
n.tick()
check("notices: and again when almost empty", fb.shown[-1][0] == "Bateria do controle acabando")
count = len(fb.shown)
fb.bats = [Battery("Xbox Series", 9, charging=True)]
n.tick()
fb.bats = [Battery("Xbox Series", 9)]
n.tick()
check("notices: after charging it may warn again", len(fb.shown) == count + 1)
count = len(fb.shown)
fb.net = "none"
n.tick()
clock[0] += 3
fb.net = "full"
n.tick()
check("notices: a short internet blip shows nothing", len(fb.shown) == count)
fb.net = "none"
n.tick()
clock[0] += 10
n.tick()
check("notices: internet down after it lasts a few seconds",
      fb.shown[-1] == ("Sem internet", "", "wired-off.svg"))
fb.net = "full"
n.tick()
clock[0] += 10
n.tick()
check("notices: internet back", fb.shown[-1] == ("A internet voltou", "", "wired.svg"))
count = len(fb.shown)
lang["notifications"] = False
fb.pads = []
n.tick()
check("notices: turned off in apps.json, nothing is shown", len(fb.shown) == count)

# 9b4. Home Assistant: webhook events when the gamepad is used
from htpc import home_assistant as hass  # noqa: E402
sent = []
ha_cfg = {"home_assistant": {"url": "http://ha.local:8123/", "webhook_id": "htpc-test"}}
pads_now = ["Xbox"]
g = SimpleNamespace(connected=lambda: list(pads_now), devs={"/dev/input/event2": SimpleNamespace(name="Xbox")})
hclock = [0.0]
h = hass.HomeAssistant(g, settings=lambda: ha_cfg, post=lambda url, p: sent.append((url, p["event"], p["gamepad"])),
                       clock=lambda: hclock[0], background=False)
h.tick()
check("HA: nothing for the gamepad already there at start", sent == [])
press = GamepadEvent("/dev/input/event2", "button", "a", 1)
h.button(press)
h.button(GamepadEvent("/dev/input/event2", "button", "a", 0))
hclock[0] += 30
h.button(press)
check("HA: a press sends gamepad_activity once a minute at most",
      sent == [("http://ha.local:8123/api/webhook/htpc-test", "gamepad_activity", "Xbox")])
hclock[0] += 31
h.button(press)
check("HA: and again after a minute", len(sent) == 2)
pads_now = ["Xbox", "8BitDo"]
h.tick()
check("HA: a gamepad showing up sends gamepad_connected", sent[-1][1:] == ("gamepad_connected", "8BitDo"))
ha_cfg["home_assistant"]["enabled"] = False
hclock[0] += 120
h.button(press)
check("HA: nothing when turned off or not configured", len(sent) == 3)

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
