# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Shortcut and Linux backend tests against a fake GNOME extension and MPRIS player.

Run: dbus-run-session -- python3 tests/test_controller.py
"""
import json
import logging
import os
import sys
import pathlib
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
HOME = ("guide", "l1", "r1")
S = fakes.state


def running():
    return [w["appId"] for w in S["windows"]]


# 0. the old config format is read as the new one
cfg_loaded = config.load()[0]
check("old Portuguese apps.json is translated on load",
      cfg_loaded["apps"][0]["name"] == "YouTube" and cfg_loaded["apps"][0]["pause_on_home"] is True
      and cfg_loaded["language"] == "pt-BR")

# 1. the guide button alone is left to the app (Steam opens its menu with it)
focus_before = S["focus"]
press("guide"); time.sleep(0.2)
check("guide alone does nothing (left to the app)", S["focus"] == focus_before and S["player"] != "Paused")

# 1b. the home combo on Jellyfin while it plays: pauses, shows the launcher, Jellyfin stays open
press(*HOME); time.sleep(0.2)
check("Home + LB + RB pauses the video", S["player"] == "Paused")
check("Home + LB + RB shows the launcher", S["focus"] == "htpc-launcher")
check("Jellyfin stays open", "org.jellyfin.JellyfinDesktop" in running())

# 2. the repeat from Steam's virtual gamepad is ignored
n = len(S["log"]); press(*HOME); time.sleep(0.1)
check("a home combo repeated right away is ignored", len(S["log"]) == n)
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

# 9a1b. the combos come from apps.json ("shortcuts"), with checks
check("default combos: Home + LB + RB and Start + Select + LB + RB",
      sc.combo_label(sc.combos({})["home"]) == "Home + LB + RB"
      and sc.combo_label(sc.combos({})["close"]) == "Start + Select + LB + RB")
custom = {"shortcuts": {"home": ["guide", "a"]}}
check("a custom home combo is used, the close one stays the default",
      sc.combos(custom)["home"] == {"guide", "a"} and sc.combos(custom)["close"] == sc.CLOSE_COMBO)
check("combos that contain each other fall back to the defaults",
      sc.combos({"shortcuts": {"home": ["start", "select"], "close": ["start", "select", "a"]}}) == sc.DEFAULT_COMBOS)
check("a combo needs two buttons, no d-pad, and must not overlap the other",
      sc.combo_problem({"guide"}, sc.CLOSE_COMBO) == "too_short"
      and sc.combo_problem({"guide", "up"}, sc.CLOSE_COMBO) == "bad_button"
      and sc.combo_problem({"start", "select"}, sc.CLOSE_COMBO) == "overlap"
      and sc.combo_problem({"guide", "a"}, sc.CLOSE_COMBO) is None)
fired = []
stub2 = SimpleNamespace(windows=SimpleNamespace(hide_pointer=lambda: None),
                        guide=lambda: fired.append("home"), close=lambda: fired.append("close"))
gs2 = sc.GamepadShortcuts(stub2, settings=lambda: custom)


def press2(*buttons):
    for b in buttons:
        gs2.handle(GamepadEvent("p", "button", b, 1))
    for b in buttons:
        gs2.handle(GamepadEvent("p", "button", b, 0))


press2("guide", "l1", "r1")
press2("guide", "a")
press2(*COMBO)
check("with a custom home combo, the old one does nothing and the new one works",
      fired == ["home", "close"])

# 9a1e. app and media events for Home Assistant (cinema mode)
from htpc.backends.base import Window  # noqa: E402
from htpc import home_assistant as hass  # noqa: E402
ev_cfg = {"apps": [{"name": "Jellyfin", "id": "org.jellyfin.JellyfinDesktop"},
                   {"name": "Steam", "id": "com.valvesoftware.Steam", "extra_ids": ["steam"]}],
          "home_assistant": {"url": "http://ha.local:8123", "webhook_id": "w"}}
ev_windows = []
ev_play = ["stopped"]
ev_sent = []
ev_clock = [0.0]
events = hass.AppEvents(SimpleNamespace(windows=lambda: list(ev_windows)),
                        SimpleNamespace(playback=lambda: ev_play[0]), lambda: ev_cfg,
                        post=lambda url, payload: ev_sent.append((url, payload["event"], payload["app"])),
                        clock=lambda: ev_clock[0], background=False)


def ev_tick():
    ev_clock[0] += hass.EVENTS_EVERY
    events.tick()


ev_windows[:] = [Window(app_id="htpc-launcher", ids=["htpc-launcher"], title="", pid=1, focused=True)]
ev_tick()
ev_windows.append(Window(app_id="org.jellyfin.JellyfinDesktop", ids=["org.jellyfin.jellyfindesktop"],
                         title="Jellyfin", pid=2, focused=False))
ev_tick()
check("events: nothing is sent without the events webhook", ev_sent == [])
ev_cfg["home_assistant"]["events_webhook_id"] = "ev"
ev_tick()
check("events: the first look sends nothing (no startup burst)", ev_sent == [])
ev_windows[0] = Window(app_id="htpc-launcher", ids=["htpc-launcher"], title="", pid=1, focused=False)
ev_windows.append(Window(app_id="steam", ids=["steam"], title="Steam", pid=3, focused=True))
ev_tick()
check("events: an app opening sends app_opened with its name",
      ev_sent == [("http://ha.local:8123/api/webhook/ev", "app_opened", "Steam")])
ev_play[0] = "playing"
ev_tick()
ev_play[0] = "paused"
ev_tick()
ev_tick()
check("events: media playing and paused, once each, with the app in front",
      [e[1:] for e in ev_sent[1:]] == [("media_playing", "Steam"), ("media_paused", "Steam")])
del ev_windows[2]
ev_play[0] = "stopped"
ev_tick()
check("events: closing it sends app_closed (and media_stopped)",
      [e[1] for e in ev_sent[3:]] == ["app_closed", "media_stopped"])
n_sent = len(ev_sent)
ev_clock[0] += 0.5
ev_play[0] = "playing"
events.tick()
check("events: checked every 2 seconds, not on every loop", len(ev_sent) == n_sent)
check("MPRIS: the real backend reads the players' state",
      backend.media().playback() == {"Playing": "playing", "Paused": "paused"}.get(S["player"], "stopped"))

# 9a1f. per-app resolution: Mutter's DisplayConfig (a fake one)
from htpc.backends.base import pick_mode, parse_mode_key  # noqa: E402
from htpc.backends.linux import display as ldisplay  # noqa: E402
mxml = pathlib.Path(tempfile.mkdtemp()) / "monitors.xml"
mxml.write_text("""<monitors version="2"><configuration><logicalmonitor><x>0</x><y>0</y><scale>1</scale>
<primary>yes</primary><monitor><monitorspec><connector>HDMI-2</connector><vendor>GSM</vendor>
<product>LG TV</product><serial>0x01</serial></monitorspec><mode><width>2560</width><height>1440</height>
<rate>59.951</rate></mode></monitor></logicalmonitor></configuration></monitors>""")
disp = ldisplay.MutterDisplay(monitors_xml=str(mxml))
dmodes = disp.modes()
check("display: the screen's modes, the current one marked",
      len(dmodes) == 7 and [m.key() for m in dmodes if m.current] == ["2560x1440@60"])
check("display: apps.json keys pick the closest mode",
      pick_mode(dmodes, "3840x2160@30").id == "3840x2160@30.000"
      and pick_mode(dmodes, "3840x2160").id == "3840x2160@30.000"
      and pick_mode(dmodes, "1920x1080@59.94").id == "1920x1080@60.000"
      and pick_mode(dmodes, "800x600") is None and pick_mode(dmodes, "junk") is None
      and parse_mode_key("2560x1440@60") == (2560, 1440, 60.0))
check("display: the default is the mode GNOME saved", disp.default_mode().id == "2560x1440@59.951")
disp.apply(pick_mode(dmodes, "3840x2160@30"))
method, config = fakes.mutter["applied"][-1]
check("display: applied 'temporary' (no confirmation, not saved), same layout and scale",
      method == 1 and config == [(0, 0, 1.0, 0, True, [("HDMI-2", "3840x2160@30.000", {})])]
      and [m.key() for m in disp.modes() if m.current] == ["3840x2160@30"])
check("display: nothing saved: the monitor's preferred mode",
      ldisplay.MutterDisplay(monitors_xml="/nonexistent").default_mode().id == "3840x2160@30.000")
disp.apply(disp.default_mode())
check("display: back to the default", fakes.mutter["current"] == "2560x1440@59.951")

# 9a1g. updates: GitHub releases and Flatpak
from htpc import updates as up  # noqa: E402
import tarfile as _tar  # noqa: E402
check("updates: versions compare like releases (betas before the final one)",
      up.is_newer("0.1.0-beta.6", "0.1.0-beta.5") and not up.is_newer("0.1.0-beta.5", "0.1.0-beta.5")
      and up.is_newer("0.1.0", "0.1.0-beta.9") and up.is_newer("0.1.0-beta.10", "0.1.0-beta.9")
      and not up.is_newer("0.1.0-beta.4", "0.1.0-beta.5") and up.is_newer("v0.2.0-beta.1", "0.1.0"))
fake_releases = [
    {"tag_name": "v0.1.0-beta.7", "draft": True, "assets": []},
    {"tag_name": "v0.1.0-beta.6", "draft": False, "prerelease": True, "body": "notes", "html_url": "page",
     "assets": [{"name": "htpc-launcher-0.1.0-beta.6.tar.gz", "browser_download_url": "https://x/r.tar.gz"}]},
]
rel = up.latest_release(lambda url: fake_releases)
check("updates: the newest published release (drafts skipped), with its .tar.gz",
      rel == {"version": "0.1.0-beta.6", "tag": "v0.1.0-beta.6", "url": "https://x/r.tar.gz",
              "notes": "notes", "page": "page"})
# a release archive with an install.sh that leaves a mark, and a newer extension
src = pathlib.Path(tempfile.mkdtemp()) / "htpc-launcher-0.1.0-beta.6"
(src / "gnome-extension" / "htpc-launcher@htpc").mkdir(parents=True)
(src / "gnome-extension" / "htpc-launcher@htpc" / "metadata.json").write_text('{"version": 99}')
(src / "install.sh").write_text("echo installed > ../mark\n")
archive = src.parent / "r.tar.gz"
with _tar.open(archive, "w:gz") as t:
    t.add(src, arcname=src.name)
work = pathlib.Path(tempfile.mkdtemp()) / "update"
old_ext = up.installed_extension_dir
fake_ext = pathlib.Path(tempfile.mkdtemp())
(fake_ext / "metadata.json").write_text('{"version": 6}')
up.installed_extension_dir = lambda: str(fake_ext)
result = up.install_release(rel, fetch=lambda url, target: __import__("shutil").copy(archive, target),
                            workdir=str(work))
check("updates: install downloads, extracts and runs install.sh; tells when the extension changed",
      result == {"version": "0.1.0-beta.6", "extension_changed": True} and (work / "mark").exists())
(src / "install.sh").write_text("echo boom >&2; exit 3\n")
with _tar.open(archive, "w:gz") as t:
    t.add(src, arcname=src.name)
try:
    up.install_release(rel, fetch=lambda url, target: __import__("shutil").copy(archive, target), workdir=str(work))
    install_error = None
except RuntimeError as e:
    install_error = str(e)
up.installed_extension_dir = old_ext
check("updates: a failing install.sh raises with its last lines", install_error == "boom")


def fake_flatpak(cmd, **kw):
    out = {"--user": "", "--system": "Application ID\tName\norg.jellyfin.JellyfinDesktop\tJellyfin\n"
           "com.valvesoftware.Steam\tSteam\n"}
    return SimpleNamespace(returncode=0, stdout=out.get(cmd[3], ""), stderr="")


check("updates: Flatpaks with updates, user and system, by name",
      up.flatpak_updates(fake_flatpak) == [("org.jellyfin.JellyfinDesktop", "Jellyfin"),
                                          ("com.valvesoftware.Steam", "Steam")])

# 9a1h. audio output through pactl (a fake one)
from htpc.backends.linux.audio import PulseAudio  # noqa: E402
from htpc.backends.linux import bluetooth as lbt  # noqa: E402
pa_state = {"default": "alsa_output.hdmi", "moved": []}
pa_sinks = [
    {"name": "alsa_output.hdmi", "description": "TV (HDMI)", "properties": {"device.bus": "pci"}},
    {"name": "bluez_output.AA_BB.1", "description": "JBL Flip 5", "properties": {"device.bus": "bluetooth"}},
]


def fake_pactl(cmd):
    if cmd[1:] == ["-f", "json", "list", "sinks"]:
        return json.dumps(pa_sinks)
    if cmd[1] == "get-default-sink":
        return pa_state["default"] + "\n"
    if cmd[1] == "set-default-sink":
        pa_state["default"] = cmd[2]
        return ""
    if cmd[1:] == ["list", "short", "sink-inputs"]:
        return "12\t0\t34\tPipeWire\tfloat32le 2ch 48000Hz\n"
    if cmd[1] == "move-sink-input":
        pa_state["moved"].append((cmd[2], cmd[3]))
        return ""
    raise AssertionError(cmd)


pa = PulseAudio(run=fake_pactl)
outs = pa.outputs()
check("audio: the outputs, the current one first and marked, Bluetooth ones flagged",
      [(o.name, o.current, o.bluetooth) for o in outs] == [("TV (HDMI)", True, False), ("JBL Flip 5", False, True)])
pa.set_output("bluez_output.AA_BB.1")
check("audio: choosing one makes it the default and moves what is playing",
      pa_state["default"] == "bluez_output.AA_BB.1" and pa_state["moved"] == [("12", "bluez_output.AA_BB.1")]
      and pa.outputs()[0].name == "JBL Flip 5")
check("bluetooth: keyboards and mice by icon, device class or name",
      lbt.device_kind({"Icon": "input-keyboard"}) == "keyboard" and lbt.device_kind({"Class": 0x002540}) == "keyboard"
      and lbt.device_kind({"Class": 0x002580}) == "mouse" and lbt.device_kind({"Name": "MX Mouse"}) == "mouse"
      and lbt.device_kind({"Class": 0x002508}) == "gamepad" and lbt.device_kind({"Name": "JBL Flip"}) == "audio"
      and lbt.device_kind({"Name": "Fridge"}) == "")
check("bluetooth: speakers and headphones are told apart from gamepads",
      lbt.is_audio({"Icon": "audio-headphones"}) and lbt.is_audio({"Class": 0x240414})
      and lbt.is_audio({"Name": "JBL Flip 5"}) and not lbt.is_audio({"Name": "Xbox Wireless Controller"}))

# 9a1d. volume: Start + Select + Up / Down, repeating while held
vol = []
vclock = [0.0]
stub3 = SimpleNamespace(windows=SimpleNamespace(hide_pointer=lambda: None), guide=lambda: vol.append("home"),
                        close=lambda: vol.append("close"), volume=lambda d: vol.append(d))
gs3 = sc.GamepadShortcuts(stub3, settings=lambda: {}, clock=lambda: vclock[0])


def ev3(b, v):
    gs3.handle(GamepadEvent("p", "button", b, v))


ev3("start", 1); ev3("select", 1); ev3("up", 1)
check("Start + Select + Up raises the volume once", vol == [1])
check("while held, the service polls quickly", gs3.timeout(2.0) <= sc.REPEAT_DELAY)
vclock[0] += sc.REPEAT_DELAY + 0.01
gs3.tick()
vclock[0] += sc.REPEAT_EVERY + 0.01
gs3.tick()
check("holding it keeps raising", vol == [1, 1, 1])
ev3("up", 0)
vclock[0] += 1
gs3.tick()
check("releasing the arrow stops it", vol == [1, 1, 1] and gs3.timeout(2.0) == 2.0)
ev3("down", 1); ev3("down", 0)
check("Start + Select + Down lowers it", vol[-1] == -1)
ev3("start", 0); ev3("select", 0)
ev3("up", 1); ev3("up", 0)
check("the arrow alone does nothing", vol[-1] == -1 and len(vol) == 4)
check("a custom combo can't be just Start + Select (it would fire on the way to the volume)",
      sc.combo_problem({"start", "select"}, {"guide", "l1", "r1"}) == "volume")

# the Linux side: wpctl (a fake one on PATH), unmuted when raising
fakebin = pathlib.Path(tempfile.mkdtemp())
volfile = fakebin / "vol"
volfile.write_text("0.50 muted")
(fakebin / "wpctl").write_text("""#!/bin/sh
read v m < "$(dirname "$0")/vol"
case "$1" in
  set-mute) echo "$v unmuted" > "$(dirname "$0")/vol" ;;
  set-volume) python3 -c "import sys; v=float(sys.argv[1]); s=sys.argv[2]; d=float(s[:-1]); v=v+d if s.endswith('+') else v-d; print(f'{min(1.0, max(0.0, v)):.2f}', sys.argv[3])" "$v" "$5" "$m" > "$(dirname "$0")/vol" ;;
  get-volume) if [ "$m" = muted ]; then echo "Volume: $v [MUTED]"; else echo "Volume: $v"; fi ;;
esac
""")
(fakebin / "wpctl").chmod(0o755)
old_path = os.environ["PATH"]
os.environ["PATH"] = f"{fakebin}:{old_path}"
from htpc.backends.linux.system import LinuxSystem  # noqa: E402
lin = LinuxSystem()
down = lin.change_volume(-0.05)
up = lin.change_volume(0.05)
for _ in range(15):
    top = lin.change_volume(0.05)
os.environ["PATH"] = old_path
check("Linux: lowering keeps it muted, raising unmutes, and it stops at 100%",
      down == (0.45, True) and up == (0.5, False) and top == (1.0, False))

# the whole thing through the real Shortcuts: level on GNOME's indicator
fakes.state.pop("osd", None)
real = sc.Shortcuts(backend)
real.system = SimpleNamespace(change_volume=lambda step: (0.3, False))
real.volume(1)
real.system = SimpleNamespace(change_volume=lambda step: (0.0, True))
real.volume(-1)
check("the volume level shows on GNOME's indicator, with the right icon",
      fakes.state.get("osd") == [("audio-volume-low-symbolic", 0.3), ("audio-volume-muted-symbolic", 0.0)])

# 9a1c. Bluetooth pairing through BlueZ (a fake org.bluez on the session bus)
from htpc.backends.linux import bluetooth as lbt  # noqa: E402
bt = lbt.BluezBluetooth(bus="SESSION", sysfs=None)
check("bluetooth: the adapter is found", bt.available())
_nohci = pathlib.Path(tempfile.mkdtemp())
check("bluetooth: no adapter in the kernel: not available at once, without asking BlueZ",
      not lbt.BluezBluetooth(bus="SESSION", sysfs=str(_nohci)).available()
      and not lbt.BluezBluetooth(bus="SESSION", sysfs="/nonexistent").available())
(_nohci / "hci0").mkdir()
check("bluetooth: an adapter in the kernel: BlueZ is asked", lbt.BluezBluetooth(bus="SESSION", sysfs=str(_nohci)).available())
bt.start_search()
check("bluetooth: searching powers the adapter on and starts discovery",
      fakes.bluez["adapter"] == {"Powered": True, "Discovering": True})
found = {d.address: d for d in bt.devices()}
check("bluetooth: gamepads are told apart by icon, device class or name",
      found["AA:AA:AA:AA:AA:AA"].gamepad and found["DD:DD:DD:DD:DD:DD"].gamepad
      and not found["BB:BB:BB:BB:BB:BB"].gamepad and not found["CC:CC:CC:CC:CC:CC"].has_name)
bt.pair("AA:AA:AA:AA:AA:AA")
xbox = fakes.bluez["devices"]["AA:AA:AA:AA:AA:AA"]
check("bluetooth: pairing pairs, trusts and connects",
      xbox["Paired"] and xbox["Trusted"] and xbox["Connected"])
check("bluetooth: paired and connected ones come first", bt.devices()[0].address == "AA:AA:AA:AA:AA:AA")
fakes.bluez["fail_pair"].add("DD:DD:DD:DD:DD:DD")
try:
    bt.pair("DD:DD:DD:DD:DD:DD")
    pair_error = None
except Exception as e:  # noqa: BLE001
    pair_error = e
check("bluetooth: a failed pairing raises", pair_error is not None
      and not fakes.bluez["devices"]["DD:DD:DD:DD:DD:DD"].get("Trusted"))
bt.forget("AA:AA:AA:AA:AA:AA")
check("bluetooth: forget removes the device", "AA:AA:AA:AA:AA:AA" not in fakes.bluez["devices"])
bt.stop_search()
check("bluetooth: stop ends discovery", fakes.bluez["adapter"]["Discovering"] is False)
check("bluetooth: the default backend has none", not __import__("htpc.backends.base", fromlist=["x"]).Bluetooth().available())

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
marker = pathlib.Path(tempfile.mkdtemp()) / "tv-off"
h.marker = lambda: marker
hclock[0] += 5
h.button(press)
check("HA: within the minute, a press is not sent again", len(sent) == 3)
import time as _time  # noqa: E402
_time.sleep(0.02)
marker.write_text("x")   # the launcher's "Turn off TV", after the last event sent
_time.sleep(0.02)
h.button(press)
check("HA: but right after 'Turn off TV' the next press goes at once (to wake it)",
      len(sent) == 4 and sent[-1][1] == "gamepad_activity")
h.button(press)
check("HA: and only that one", len(sent) == 4)
ha_cfg["home_assistant"]["enabled"] = False
hclock[0] += 120
h.button(press)
check("HA: nothing when turned off or not configured", len(sent) == 4)

# 9b2. the TV's state: while it is off, input only wakes it
tv_cfg = {"home_assistant": {"url": "http://ha.local:8123", "webhook_id": "htpc-test",
                             "token": "tok", "tv_entity": "media_player.tv"}}
tv_state = ["on"]
asked = []


def fake_get(url, token):
    asked.append((url, token))
    if url.endswith("/api/states"):
        return [{"entity_id": "media_player.tv", "attributes": {"friendly_name": "Sala"}},
                {"entity_id": "light.sala"}, {"entity_id": "media_player.alexa"}]
    return {"state": tv_state[0]}


check("HA: reading the TV's state needs the token and the entity",
      hass.fetch_tv_state(ha_cfg) is None and hass.fetch_tv_state(tv_cfg, fake_get) == "on"
      and asked[-1] == ("http://ha.local:8123/api/states/media_player.tv", "tok"))
tv_state[0] = "standby"
s_off = hass.fetch_tv_state(tv_cfg, fake_get)
tv_state[0] = "unavailable"
check("HA: off/standby is off; unavailable is unknown (never blocks)",
      s_off == "off" and hass.fetch_tv_state(tv_cfg, fake_get) is None)
check("HA: the media players listed for the TV picker",
      hass.media_players(tv_cfg, fake_get) == [("media_player.alexa", "media_player.alexa"),
                                               ("media_player.tv", "Sala")])
gate_path = pathlib.Path(tempfile.mkdtemp()) / "tv-gate"
woken = []
gclock = [100.0]
gate = hass.TvGate(lambda: tv_cfg, woken.append, get=fake_get, clock=lambda: gclock[0],
                   gate=lambda blocked: hass.write_gate(blocked, gate_path))
tv_state[0] = "on"
gate.check()
a_press = GamepadEvent("pad", "button", "a", 1)
a_release = GamepadEvent("pad", "button", "a", 0)
check("TV on: nothing is blocked", not gate.blocks(a_press) and not hass.input_blocked(gate_path))
tv_state[0] = "off"
gate.check()
check("TV off: the launcher sees the gate closed", hass.input_blocked(gate_path))
first = gate.blocks(a_press)
check("TV off: the first press is swallowed and wakes the TV", first and woken == [a_press])
gclock[0] += 2
check("TV off: more presses are swallowed but do not ask again right away",
      gate.blocks(GamepadEvent("pad", "button", "b", 1)) and gate.blocks(GamepadEvent("pad", "axis", "lx", 0.9))
      and len(woken) == 1)
check("TV off: releases and a stick back in the middle go through",
      not gate.blocks(a_release) and not gate.blocks(GamepadEvent("pad", "axis", "lx", 0.1)))
gclock[0] += hass.WAKE_RETRY
gate.blocks(a_press)
check("TV still off a while later: a press asks again", len(woken) == 2)
tv_state[0] = "on"
gate.check()
check("TV on again: input goes through and the gate opens",
      not gate.blocks(a_press) and not hass.input_blocked(gate_path) and len(woken) == 2)
# Home Assistant lost the TV (new IP...): it stays "off" however often it's woken
tv_state[0] = "off"
gate.check()
woken.clear()
for _ in range(hass.GIVE_UP_WAKES):
    gclock[0] += hass.WAKE_RETRY
    gate.blocks(a_press)
check("TV 'off' but not waking: the first wakes are sent and block",
      len(woken) == hass.GIVE_UP_WAKES and hass.input_blocked(gate_path))
gclock[0] += hass.WAKE_RETRY
gave_up = not gate.blocks(a_press)
check("after that many wakes in a minute, the gamepad is no longer blocked (launcher too)",
      gave_up and not hass.input_blocked(gate_path) and not gate.blocks(a_press))
gate.check()
check("and the next state checks keep it open while distrusted", not hass.input_blocked(gate_path))
gclock[0] += hass.DISTRUST_FOR + 1
gate.check()
check("after a while it trusts Home Assistant again", hass.input_blocked(gate_path))
tv_state[0] = "on"
gate.check()
tv_state[0] = "off"
gate.check()


def unreachable(url, token):
    raise OSError("no route")


gate.get = unreachable
gate.check()
check("HA unreachable: unknown, nothing blocked", not gate.blocks(a_press) and not hass.input_blocked(gate_path))
hass.write_gate(True, gate_path, now=lambda: time.time() - 60)
check("an old gate file (service not running) does not block the launcher", not hass.input_blocked(gate_path))
h.last_activity = hclock[0]
before = len(sent)
ha_cfg["home_assistant"]["enabled"] = True
h.wake(a_press)
check("HA: a wake press is sent even inside the once-a-minute limit",
      len(sent) == before + 1 and sent[-1][1] == "gamepad_activity")

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
