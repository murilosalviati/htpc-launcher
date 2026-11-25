# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Launcher tests: runs the real launcher under Xvfb against a fake GNOME extension,
drives it like a gamepad would, checks open/resume and edit mode, and saves screenshots.

Run: xvfb-run -s "-screen 0 1920x1080x24" dbus-run-session -- python3 tests/test_launcher.py
Screenshots go to $TMPDIR/htpc-screenshots. For the icon checks, HOME should contain
~/.local/share/htpc-launcher/app-icons/{jellyfin,moonlight,steam,youtube}.png and a
~/.local/share/applications/org.example.Player.desktop (Name=Example Player,
StartupWMClass=example-player).
"""
import json
import os
import pathlib
from types import SimpleNamespace as NS2
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "launcher"))
sys.path.insert(0, os.path.dirname(__file__))

# Start from a config in the OLD (Portuguese) format: the launcher must convert it,
# keep the Portuguese UI, and save it in the new format.
cfgdir = tempfile.mkdtemp()
os.makedirs(f"{cfgdir}/htpc-launcher")
cfg = json.load(open(os.path.join(ROOT, "config", "apps.json")))
legacy = {"name": "nome", "launch": "abrir", "icon": "icone", "extra_ids": "outros_ids", "close": "fechar",
          "close_timeout": "espera_fechar", "pause_on_home": "pausar_ao_sair",
          "close_on_second_press": "fechar_em_dois_toques", "preferred_windows": "janelas_preferidas"}
cfg.pop("language")
for a in cfg["apps"]:
    a["launch"] = ["true"]        # harmless commands for the test
    if "on_resume" in a:
        a["on_resume"] = ["true"]
    a["icon"] = a["icon"].replace("/app-icons/", "/icones-apps/")
cfg["apps"] = [{legacy.get(k, k): v for k, v in a.items()} for a in cfg["apps"]]
json.dump(cfg, open(f"{cfgdir}/htpc-launcher/apps.json", "w"))
os.environ["XDG_CONFIG_HOME"] = cfgdir

import fakes  # noqa: E402

fakes.state["windows"] = [w for w in fakes.state["windows"] if w["appId"] == "org.jellyfin.JellyfinDesktop"]
fakes.state["focus"] = "htpc-launcher"
# Steam opens three windows; the last one used is "Friends List".
for title in ("Friends List", "Special Offers", "Steam"):
    fakes.state["windows"].insert(0, {"appId": "com.valvesoftware.Steam", "ids": ["com.valvesoftware.steam", "steam", "steamwebhelper"],
                                      "title": title, "pid": 0, "minimized": False})
fakes.start()
time.sleep(0.4)

import launcher  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "htpc-screenshots")
os.makedirs(OUT, exist_ok=True)
ok = True


def check(name, cond):
    global ok
    print(("OK     " if cond else "FAILED ") + name, flush=True)
    ok &= bool(cond)


def screenshot(win, name):
    p = Gtk.WidgetPaintable.new(win)
    snap = Gtk.Snapshot()
    p.snapshot(snap, win.get_width(), win.get_height())
    node = snap.to_node()
    if node is None:   # caught mid-layout (it happens under load): no picture this time
        print(f"(screenshot {name} skipped: nothing drawn yet)", flush=True)
        return
    tex = win.get_native().get_renderer().render_texture(node, None)
    tex.save_to_png(f"{OUT}/{name}.png")


state = {}
orig_init = launcher.Launcher.__init__


def init(self, app):
    # Endless CSS animations keep the software renderer under Xvfb busy;
    # the tests check classes, not motion.
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    orig_init(self, app)
    state["l"] = self


launcher.Launcher.__init__ = init
launcher.RESUME_DELAY = 300
launcher.PRESS_DELAY = 0  # act right away; the push animation still plays

steps = []


def step(delay_ms):
    def dec(f):
        steps.append((delay_ms, f))
        return f
    return dec


def L():
    return state["l"]


def saved_apps():
    return json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))["apps"]


@step(1500)
def s1():
    l = L()
    saved = json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))
    check("old apps.json is converted and saved in the new format",
          "name" in saved["apps"][0] and "nome" not in saved["apps"][0] and saved["language"] == "pt-BR")
    check("icon paths move from icones-apps/ to app-icons/", saved["apps"][0]["icon"].endswith("/app-icons/youtube.png"))
    check("window fills the screen", l.win.get_width() >= 1280)
    check("focus starts on the first app", l.win.get_focus() is l.tiles[0])
    check("Jellyfin shows as open, in Portuguese", l.tiles[1].status.get_label() == "aberto")
    screenshot(l.win, "1-home")
    check("edge sizes follow the screen: scale 1 on 1920×1080", abs((l.edge_scale or 0) - 1.0) < 0.01)
    l.apply_edge_scale(2.0)
    check("on a screen twice as big, the edge icons double", l.weather_icon.get_pixel_size() == 144
          and l.net_icon.get_pixel_size() == 84 and all(i.get_pixel_size() == 56 for i in l.footer_images))
    from gi.repository import Gio as _Gio
    check("edge icons are drawn from the vector at their size (GIcon, not a stretched file)",
          all(isinstance(i.get_gicon(), _Gio.FileIcon) for i in [l.net_icon, l.pad_icon, *l.footer_images]))
    l.apply_edge_scale(1.0)


@step(300)
def s2():
    l = L()
    l.move(1, 0)
    check("right goes to the second app", l.win.get_focus() is l.tiles[1])
    n = len(fakes.state["log"])
    l.press()
    check("opening a running app calls Activate (resume)", ("Activate", ("org.jellyfin.JellyfinDesktop",)) in fakes.state["log"][n:])
    check("a running app is not started again", "org.jellyfin.JellyfinDesktop" not in l.opening)


@step(300)
def s3():
    l = L()
    l.move(-1, 0)
    l.press()
    check("opening a closed app shows 'abrindo…'", l.tiles[0].status.get_label() == "abrindo…")
    check("the opening tile pulses (css class 'opening')", l.tiles[0].has_css_class("opening"))
    check("pushing a tile plays the press animation", l.tiles[0].has_css_class("pressed"))
    before = dict(l.opening)
    l.press()
    check("pressing again while it opens does not start another", l.opening == before)
    check("opening an app asks for full screen", "rocks.shy.VacuumTube" in fakes.state.get("fullscreen", []))


@step(300)
def s3b():
    """Opened, then closed with the gamepad shortcut while the launcher was behind it."""
    l = L()
    yt = {"appId": "rocks.shy.VacuumTube", "ids": ["rocks.shy.vacuumtube"], "title": "YouTube", "pid": 0, "minimized": False}
    fakes.state["windows"].append(yt)
    l._check_opening()
    fakes.state["windows"].remove(yt)
    l._check_opening()
    l.refresh_status()
    check("an app closed right after opening does not go back to 'abrindo…'",
          l.tiles[0].status.get_label() == "" and "rocks.shy.VacuumTube" not in l.opening)
    check("and it stops pulsing", not l.tiles[0].has_css_class("opening"))
    check("the press animation ends by itself", not l.tiles[0].has_css_class("pressed"))


@step(300)
def s4():
    l = L()
    for _ in range(4):
        l.move(1, 0)
    check("does not go past the last app", l.win.get_focus() is l.tiles[-1])
    l.move(0, 1)
    check("down from the apps stays there when nothing is below", l.win.get_focus() is l.tiles[-1])
    l.move(0, -1)
    check("up goes to the round buttons at the top right (closest one)",
          l.win.get_focus() in (l.btn_settings, l.btn_power))
    l.move(-1, 0)
    for _ in range(3):
        l.move(1, 0)
    check("right along the top reaches the power button", l.win.get_focus() is l.btn_power)


@step(400)
def s4b():
    screenshot(L().win, "2-power-focused")


@step(100)
def s5():
    l = L()
    l.press()
    check("the power button opens its menu: restart, shut down (no TV without Home Assistant)",
          len(l.overlays) == 1 and [b.label.get_label() for b in l.power_options]
          == [l.t("restart_computer"), l.t("power_off_computer")])
    check("default focus is Cancel", l.win.get_focus() is l.overlays[-1]["rows"][-1][0])
    l.move(0, 1)
    check("down inside the menu stays in the menu", l.win.get_focus() is l.overlays[-1]["rows"][-1][0])


@step(400)
def s6():
    l = L()
    screenshot(l.win, "3-confirm-power-off")
    l.back()
    check("B closes the menu", not l.overlays)
    check("focus returns to the power button", l.win.get_focus() is l.btn_power)
    l.move(0, 1)
    check("down goes back to the apps", l.win.get_focus() in l.tiles)
    l.move(0, 1)
    check("down from the apps stays on the apps", l.win.get_focus() in l.tiles)


@step(300)
def s7():
    l = L()
    steam = next(t for t in l.tiles if t.app["name"] == "Steam")
    steam.grab_focus()
    state["log_before_steam"] = len(fakes.state["log"])
    fakes.state["activated"] = None
    l.press()
    check("running Steam: raises the 'Steam' window, not 'Friends List'", fakes.state.get("activated") == "Steam")
    check("running Steam is not started again", "com.valvesoftware.Steam" not in l.opening)
    check("Steam is not forced to full screen (Big Picture already is; its other windows should not be)",
          "com.valvesoftware.Steam" not in fakes.state.get("fullscreen", []))


@step(600)
def s7b():
    calls = [c for c in fakes.state["log"][state["log_before_steam"]:] if c[0] == "ActivatePreferring"]
    check("after on_resume (Big Picture), the Steam window is raised again", len(calls) >= 2)


@step(300)
def s8():
    l = L()
    from gi.repository import Gio

    class Net:
        def __init__(self, ok, c):
            self.ok, self.c = ok, c

        def get_network_available(self):
            return self.ok

        def get_connectivity(self):
            return self.c

    real = l.network
    l.network = Net(True, Gio.NetworkConnectivity.FULL); l._update_network()
    check("connected: icon only, no text", l.network_state == "on" and not l.net_text.get_visible())
    l.network = Net(True, Gio.NetworkConnectivity.LIMITED); l._update_network()
    check("limited internet shows text", l.network_state == "limited" and l.net_text.get_label() == "internet limitada")
    l.network = Net(False, Gio.NetworkConnectivity.LOCAL); l._update_network()
    check("no internet shows text", l.network_state == "off" and l.net_text.get_visible())
    state["real_network"] = real


@step(500)
def s9():
    screenshot(L().win, "4-no-internet")
    L().network = state["real_network"]
    L()._update_network()


# ---------------- edit mode ----------------

@step(300)
def e1():
    l = L()
    l.tiles[0].grab_focus()
    l.move(0, -1)
    check("up from the first app reaches the top buttons", l.win.get_focus() in (l.btn_settings, l.btn_power))
    l.btn_settings.grab_focus()
    l.press()
    f = l.settings_fields
    check("the gear opens Settings with apps, background, location, temperature and language",
          len(l.overlays) == 1 and list(f) == ["apps", "background", "location", "unit", "language", "notifications", "audio", "shortcuts", "home_assistant", "jellyfin"])
    check("Settings shows the current values",
          f["background"].value.get_label() == "Meia-noite" and f["unit"].value.get_label() == "°C"
          and f["language"].value.get_label() == "Português (Brasil)"
          and f["location"].value.get_label() == "Desligado (sem clima)")
    check("focus starts on Apps", l.win.get_focus() is f["apps"])
    check("on-screen notices start on", f["notifications"].value.get_label() == "Ligado")
    l._toggle_notifications()
    check("Ⓐ on notices turns them off and saves it", f["notifications"].value.get_label() == "Desligado"
          and json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))["notifications"] is False)
    l._toggle_notifications()
    check("Settings has a 'Fechar o launcher' button next to Close",
          l.settings_quit.get_label() == "Fechar o launcher" and l.settings_quit in l.overlays[-1]["rows"][-1])
    quits = []
    real_quit = l.quit_launcher
    l.quit_launcher = lambda: quits.append(1)
    l.settings_quit.grab_focus()
    l.press()
    check("closing the launcher asks first, focused on Cancel",
          len(l.overlays) == 2 and l.win.get_focus() is l.overlays[-1]["rows"][0][0] and not quits)
    l.move(1, 0)
    l.press()
    check("confirming closes the launcher", quits == [1])
    l.quit_launcher = real_quit
    f["apps"].grab_focus()
    l.press()
    check("Apps closes Settings and enters edit mode", l.editing and l.add_tile is not None and not l.overlays)
    check("the hint switches to edit mode", "Modo de edição" in l.hint.get_label())
    check("the button becomes 'Concluir'", l.btn_settings.label.get_label() == "Concluir")


@step(300)
def b1():
    l = L()
    l.open_settings(focus="background")
    l.press()
    swatches = [b for row in l.overlays[-1]["rows"] for b in row]
    check("Settings → Background offers 9 colors", len(swatches) == 9)
    check("focus starts on the current color", l.win.get_focus() is swatches[0] and l.theme == "midnight")
    l.move(1, 0)
    check("moving the focus previews the color", l.theme == "ocean")
    l.back()
    check("Ⓑ goes back to the saved color and to Settings", l.theme == "midnight" and len(l.overlays) == 1)


@step(300)
def b2():
    l = L()
    l.press()
    l.move(0, 1)  # second row, first column: aurora
    l.press()
    saved = json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))
    check("Ⓐ keeps the color and saves it to apps.json", l.theme == "aurora" and saved.get("background") == "aurora" and len(l.overlays) == 1)
    check("Settings shows the new color", l.settings_fields["background"].value.get_label() == "Aurora")


@step(500)
def b3():
    screenshot(L().win, "5b-background-aurora")
    L().press()


@step(500)
def b4():
    l = L()
    screenshot(l.win, "5c-background-picker")
    l.back()
    l.back()


@step(500)
def e2():
    l = L()
    screenshot(l.win, "5-edit-mode")
    l.tiles[2].grab_focus()
    l.press()
    check("Ⓐ on an app opens the editor", len(l.overlays) == 1 and l.editor["index"] == 2)
    check("the editor starts on Name", l.win.get_focus() is l.field_name)


@step(500)
def e3():
    l = L()
    screenshot(l.win, "6-editor")
    l.press()
    top = l.overlays[-1]
    check("Name opens the on-screen keyboard", "type" in top)
    for _ in range(20):
        l.other_button("x")
    for c in "jogos":
        top["type"](c)
    l.other_button("y")
    top["type"]("2")


@step(500)
def e4():
    l = L()
    screenshot(l.win, "7-keyboard")
    l.overlays[-1]["enter"]()
    check("keyboard: auto capital, X deletes, Y types a space", l.editor["draft"]["name"] == "Jogos 2")
    l.move(0, 1)
    l.move(0, 1)
    check("down reaches the Icon field", l.win.get_focus() is l.field_icon)
    l.press()
    rows = l.overlays[-1]["rows"]
    check("the icon picker shows the app's icon plus the 4 in the folder", sum(len(r) for r in rows) == 5)


@step(500)
def e5():
    l = L()
    screenshot(l.win, "8-icon-picker")
    l.overlays[-1]["rows"][0][1].grab_focus()
    l.press()
    check("the chosen icon goes into the draft", l.editor["draft"].get("icon", "").endswith("app-icons/jellyfin.png"))
    l.overlays[-1]["rows"][-1][0].grab_focus()
    l.press()  # Save
    a = saved_apps()[2]
    check("Save writes the name and icon to apps.json", a["name"] == "Jogos 2" and a["icon"].endswith("jellyfin.png"))
    check("Save keeps the app and its settings", a["id"] == "com.moonlight_stream.Moonlight" and a.get("close_on_second_press") is True)
    check("after saving, focus is back on the edited app", l.win.get_focus() is l.tiles[2] and not l.overlays)


@step(300)
def e6():
    l = L()
    l.add_tile.grab_focus()
    l.press()
    check("+ Add opens a new-app editor, on the Application field", l.editor["index"] is None and l.win.get_focus() is l.field_app)
    l.overlays[-1]["rows"][-1][0].grab_focus()
    l.press()
    check("saving without an app shows an error", l.editor_error.get_visible() and len(l.overlays) == 1)
    l.field_app.grab_focus()
    l.press()
    buttons = [b for row in l.overlays[-1]["rows"] for b in row]
    names = [b.get_child().get_last_child().get_label() for b in buttons]
    check("the app list has installed apps (Flatpak and the user's .desktop)", "Example Player" in names and "rocks.shy.VacuumTube" in names)
    state["example_button"] = buttons[names.index("Example Player")]


@step(500)
def e7():
    l = L()
    screenshot(l.win, "9-app-picker")
    state["example_button"].grab_focus()
    l.press()
    d = l.editor["draft"]
    check("the chosen app fills id, command and name", d["id"] == "org.example.Player" and d["launch"][:2] == ["gio", "launch"] and d["name"] == "Example Player")
    check("the chosen app keeps its WM_CLASS as an extra id", d.get("extra_ids") == ["example-player"])
    l.overlays[-1]["rows"][-1][0].grab_focus()
    l.press()
    check("the new app goes to the end of the list", saved_apps()[-1]["id"] == "org.example.Player" and len(l.tiles) == 5)
    check("with 5 apps + Add, the grid wraps onto 2 rows", len(l.tile_rows) == 2)


@step(500)
def e8():
    l = L()
    screenshot(l.win, "10-five-apps")
    l.tiles[0].grab_focus()
    l.press()
    remove = l.overlays[-1]["rows"][-1][1]
    check("the editor of an existing app has Remove", remove.get_label() == "Remover")
    remove.grab_focus()
    l.press()
    check("Remove asks for confirmation, focused on Cancel", len(l.overlays) == 2 and l.win.get_focus() is l.overlays[-1]["rows"][0][0])
    l.move(1, 0)
    l.press()
    ids = [a["id"] for a in saved_apps()]
    check("the removed app leaves apps.json", "rocks.shy.VacuumTube" not in ids and len(ids) == 4)
    check("the screen reflows: 4 apps + Add on one row", len(l.tiles) == 4 and len(l.tile_rows) == 1 and not l.overlays)
    check("focus goes to the app now in that place", l.win.get_focus() is l.tiles[0])


@step(500)
def e9():
    l = L()
    screenshot(l.win, "11-after-remove")
    l.back()
    check("Ⓑ leaves edit mode", not l.editing and l.add_tile is None and l.btn_settings.label.get_label() == "Configurações")


@step(300)
def n1():
    """Gamepad navigation through the backend's normalized events."""
    from htpc.backends.base import GamepadEvent as E
    l = L()
    nav = l.navigator
    nav.active = lambda: True
    l.tiles[0].grab_focus()
    nav.handle(E("pad", "button", "right", 1)); nav.handle(E("pad", "button", "right", 0))
    check("gamepad: d-pad right moves to the next app", l.win.get_focus() is l.tiles[1])
    nav.handle(E("pad", "axis", "lx", -0.9)); nav.handle(E("pad", "axis", "lx", 0.0))
    check("gamepad: left stick moves back", l.win.get_focus() is l.tiles[0])
    nav.handle(E("pad", "axis", "lx", 0.3))
    check("gamepad: a small stick movement is ignored", l.win.get_focus() is l.tiles[0])
    nav.handle(E("pad", "button", "up", 1)); nav.handle(E("pad", "button", "up", 0))
    check("gamepad: d-pad up reaches the top buttons", l.win.get_focus() in l.top_buttons)
    l.btn_power.grab_focus()
    nav.handle(E("pad", "button", "a", 1))
    check("gamepad: A presses the focused button", len(l.overlays) == 1)
    nav.handle(E("pad", "button", "b", 1))
    check("gamepad: B goes back", not l.overlays)

    # Gamepad indicator next to the Wi-Fi icon.
    real = l.gamepads.connected
    l.gamepads.connected = lambda: []
    l._update_gamepads()
    check("indicator: no gamepad shows the dimmed icon without a number",
          not l.pad_count.get_visible())
    l.gamepads.connected = lambda: ["Xbox"]
    l._update_gamepads()
    check("indicator: one gamepad shows the icon without a number", not l.pad_count.get_visible())
    l.gamepads.connected = lambda: ["Xbox", "8BitDo", "PS4"]
    l._update_gamepads()
    check("indicator: three gamepads show 3",
          l.pad_count.get_visible() and l.pad_count.get_label() == "3")
    from htpc.backends.base import Battery
    l.gamepads.batteries = lambda: [Battery("Xbox", 80), Battery("8BitDo", level="low", charging=True)]
    l.gamepads.connected = lambda: ["Xbox", "8BitDo"]
    l._update_gamepads()
    icons = []
    c = l.battery_box.get_first_child()
    while c is not None:
        icons.append(c.get_gicon().get_file().get_basename())
        c = c.get_next_sibling()
    check("one battery icon per wireless gamepad, charging shown with a bolt",
          icons == ["battery-3.svg", "battery-charging.svg"] and l.battery_box.get_visible())
    l.tiles[0].grab_focus()


@step(300)
def n2():
    l = L()
    screenshot(l.win, "9-two-gamepads")
    l.gamepads.batteries = lambda: []
    l.gamepads.connected = lambda: []
    l._update_gamepads()


# ---------------- weather, temperature unit, language, network kind ----------------

from htpc import weather as W  # noqa: E402

GEO = {"results": [
    {"name": "Araranguá", "latitude": -28.9, "longitude": -49.5, "country_code": "BR", "admin1": "Santa Catarina"},
    {"name": "Campinas", "latitude": -3.77, "longitude": -39.7, "country_code": "BR", "admin1": "Ceará"},
    {"name": "Campinas", "latitude": -22.9, "longitude": -47.06, "country_code": "BR", "admin1": "São Paulo"},
]}


def fake_fetch(url):
    state.setdefault("urls", []).append(url)
    if "offline" in url.lower():
        raise W.Unreachable("no network")
    if "viacep" in url:
        return {"erro": "true"} if "99999999" in url else {"localidade": "Campinas", "uf": "SP"}
    if "geocoding" in url:
        return GEO if "Campinas" in url else {}
    if "forecast" in url:
        f = "fahrenheit" in url
        return {"current": {"temperature_2m": 81.3 if f else 27.4, "weather_code": 2, "is_day": 1}}
    raise AssertionError(url)


def type_location(l, text):
    l.open_settings(focus="location")
    l.press()
    top = l.overlays[-1]
    for _ in range(30):
        top["delete"]()
    for c in text:
        top["type"](c)
    top["enter"]()


@step(300)
def w1():
    l = L()
    l.weather_fetch = fake_fetch
    check("no location: the weather is hidden", not l.weather_box.get_visible())
    type_location(l, "13010-001")


@step(500)
def w2():
    l = L()
    screenshot(l.win, "13-use-place")
    title = l.overlays[-1]["backdrop"].get_first_child().get_first_child().get_label()
    check("a CEP finds its town in the right state and asks to confirm", title == "Usar Campinas, SP?")
    l.press()  # Use
    saved = json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))
    check("the location is saved with its coordinates",
          saved["weather"]["name"] == "Campinas, SP" and saved["weather"]["latitude"] == -22.9
          and saved["weather"]["query"] == "13010-001")
    check("Settings shows the place", l.settings_fields["location"].value.get_label() == "Campinas, SP")


@step(500)
def w3():
    l = L()
    check("the weather shows up: rounded temperature, place, partly cloudy by day",
          l.weather_box.get_visible() and l.weather_temp.get_label() == "27°"
          and l.weather_place.get_label() == "Campinas, SP" and l.conditions.icon == "weather-partly-day.svg")
    l.settings_fields["unit"].grab_focus()
    l.press()
    check("Ⓐ on Temperature switches to °F and saves it",
          l.settings_fields["unit"].value.get_label() == "°F"
          and json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))["temperature_unit"] == "fahrenheit")


@step(500)
def w4():
    l = L()
    check("the temperature comes in °F", l.weather_temp.get_label() == "81°")
    while l.overlays:
        l.pop_overlay()
    type_location(l, "99999-999")


@step(500)
def w5():
    l = L()
    title = l.overlays[-1]["backdrop"].get_first_child().get_first_child().get_label()
    check("a CEP that does not exist says so", "99999-999" in title and "Não encontrei" in title)
    while l.overlays:
        l.pop_overlay()
    type_location(l, "Offline")


@step(500)
def w6():
    l = L()
    title = l.overlays[-1]["backdrop"].get_first_child().get_first_child().get_label()
    check("no internet: says the service could not be reached", "Não consegui" in title)
    check("a failed search keeps the saved place", l.cfg["weather"]["name"] == "Campinas, SP")
    while l.overlays:
        l.pop_overlay()
    l.open_settings(focus="language")
    l.press()
    buttons = l.overlays[-1]["rows"][0]
    check("the language picker lists English and Português", [b.get_label() for b in buttons] == ["English", "Português (Brasil)"])
    buttons[0].grab_focus()
    l.press()


@step(500)
def w7():
    l = L()
    check("English applies right away: footer, hint and Settings",
          l.btn_settings.label.get_label() == "Settings" and l.hint.get_label().startswith("Ⓐ open")
          and l.settings_fields["language"].value.get_label() == "English"
          and l.win.get_focus() is l.settings_fields["language"])
    check("the weather is still on screen after the switch", l.weather_box.get_visible() and l.weather_temp.get_label() == "81°")
    check("the date is in English", l.date_label.get_label().split(",")[0] in
          ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))
    check("the language is saved", json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))["language"] == "en")
    screenshot(l.win, "14-settings")


@step(300)
def w8():
    l = L()
    while l.overlays:
        l.pop_overlay()
    real = l.system.connection_kind
    l.system.connection_kind = lambda: "wired"
    l._update_network()
    check("network over a cable: wired icon, not Wi-Fi", l.net_icon_name.startswith("wired"))
    l.system.connection_kind = lambda: "wifi"
    l._update_network()
    check("network over Wi-Fi: Wi-Fi icon", l.net_icon_name.startswith("wifi"))
    l.system.connection_kind = lambda: None
    l._update_network()
    check("kind unknown (e.g. disconnected): keeps the last one", l.net_icon_name.startswith("wifi"))
    l.system.connection_kind = lambda: "wired"
    l._update_network()
    l.system.connection_kind = real
    l.tiles[0].grab_focus()


@step(500)
def w9():
    screenshot(L().win, "12-home-weather")
    type_location(L(), "")


@step(300)
def w10():
    l = L()
    check("an empty location turns the weather off", "weather" not in l.cfg and not l.weather_box.get_visible()
          and l.settings_fields["location"].value.get_label() == "Off (weather hidden)")


# ---------------- Home Assistant settings and "Turn off TV" ----------------

def label_texts(widget):
    """All the label texts inside a widget, joined."""
    out = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            out.append(child.get_label())
        out.append(label_texts(child))
        child = child.get_next_sibling()
    return "\n".join(t for t in out if t)


def ha_type(l, field, text):
    """Settings → Home Assistant → field, typed on the on-screen keyboard."""
    l.open_home_assistant(focus=field)
    l.press()
    top = l.overlays[-1]
    for _ in range(60):
        top["delete"]()
    for c in text:
        top["type"](c)
    top["enter"]()


@step(300)
def tv1():
    l = L()
    while l.overlays:
        l.pop_overlay()
    check("no Home Assistant set up: no 'turn off the TV' in the power menu", not l.tv_off_available())
    l.open_settings(focus="home_assistant")
    check("Settings has a Home Assistant row saying it is not set up",
          l.settings_fields["home_assistant"].value.get_label() == l.t("ha_not_set"))
    l.press()
    f = l.ha_fields
    check("it opens the Home Assistant menu", len(l.overlays) == 2
          and list(f) == ["enabled", "url", "webhook", "events", "token", "tv", "home", "test"]
          and f["token"].value.get_label() == l.t("ha_token_missing")
          and f["tv"].value.get_label() == l.t("ha_tv_needs_token"))
    l.pop_overlay()
    ha_type(l, "url", "192.168.0.22:8123")
    check("an address without http:// is refused", "home_assistant" not in l.cfg
          and l.t("ha_bad_url") in label_texts(l.overlays[-1]["backdrop"]))
    l.pop_overlay()
    ha_type(l, "url", "http://192.168.0.22:8123/")
    check("the address is typed in lower case and saved without the trailing /",
          l.cfg["home_assistant"] == {"url": "http://192.168.0.22:8123"}
          and l.ha_fields["url"].value.get_label() == "http://192.168.0.22:8123")
    check("app and media events are off until their webhook is typed",
          l.ha_fields["events"].value.get_label() == l.t("off"))
    ha_type(l, "events", "htpc-events_1")
    check("the events webhook is saved", l.cfg["home_assistant"]["events_webhook_id"] == "htpc-events_1"
          and l.ha_fields["events"].value.get_label() == "htpc-events_1")
    ha_type(l, "events", "")
    check("and cleared again", "events_webhook_id" not in l.cfg["home_assistant"])
    ha_type(l, "webhook", "htpc-gamepad_1")
    check("the webhook id is saved: Home Assistant is set up",
          l.cfg["home_assistant"]["webhook_id"] == "htpc-gamepad_1"
          and l.settings_fields["home_assistant"].value.get_label() == l.t("ha_on_at", host="192.168.0.22:8123")
          and l.tv_off_available())


@step(500)
def tv2():
    l = L()
    from htpc import home_assistant as hass
    screenshot(l.win, "14-settings-home-assistant")
    while l.overlays:
        l.pop_overlay()
    l.btn_power.grab_focus()
    l.press()
    check("with Home Assistant, the power menu starts on 'turn off the TV'",
          [b.label.get_label() for b in l.power_options]
          == [l.t("tv_off"), l.t("restart_computer"), l.t("power_off_computer")]
          and l.win.get_focus() is l.power_options[0])


@step(400)
def tv2b():
    l = L()
    from htpc import home_assistant as hass
    screenshot(l.win, "15-power-menu")
    hass.http_post = lambda url, payload: None
    l.press()
    check("turning off the TV closes the menu and goes back to the start (first app, top of the screen)",
          not l.overlays and l.win.get_focus() is l.tiles[0] and l.scroller.get_vadjustment().get_value() == 0)


@step(400)
def tv3():
    l = L()
    from htpc import home_assistant as hass
    check("'Desligar TV' sends tv_off to the Home Assistant webhook and leaves the marker",
          hass.tv_off_marker().exists())
    sent = []
    l.ha_post = lambda url, payload: sent.append((url, payload["event"]))
    l.open_home_assistant(focus="test")
    l.press()


@step(400)
def tv4():
    l = L()
    check("the connection test posts a test event to the webhook and says it worked",
          l.t("ha_test_ok") in label_texts(l.overlays[-1]["backdrop"]))
    l.pop_overlay()

    def fail(url, payload):
        raise OSError("connection refused")
    l.ha_post = fail
    l.ha_fields["test"].grab_focus()
    l.press()


@step(400)
def tv5():
    l = L()
    check("a failed test says why", l.t("ha_test_failed", error="connection refused")
          in label_texts(l.overlays[-1]["backdrop"]))
    l.pop_overlay()
    l.ha_fields["enabled"].grab_focus()
    l.press()
    check("switching Home Assistant off takes the TV out of the power menu and keeps the address",
          l.cfg["home_assistant"].get("enabled") is False and not l.tv_off_available()
          and l.cfg["home_assistant"]["url"] == "http://192.168.0.22:8123")
    l.press()
    check("and on again brings it back", "enabled" not in l.cfg["home_assistant"] and l.tv_off_available())
    ha_type(l, "webhook", "")
    check("an empty webhook id leaves it not set up", "webhook_id" not in l.cfg["home_assistant"]
          and not l.tv_off_available())
    ha_type(l, "url", "")
    check("and with both empty the entry is gone", "home_assistant" not in l.cfg)
    while l.overlays:
        l.pop_overlay()
    # the token goes in apps.json; then the TV is picked from Home Assistant's list
    l.cfg["home_assistant"] = {"url": "http://ha.local:8123", "webhook_id": "w", "token": "tok"}
    state = {"now": "off"}

    def fake_get(url, token):
        if url.endswith("/api/states"):
            return [{"entity_id": "media_player.lg", "attributes": {"friendly_name": "TV da sala"}},
                    {"entity_id": "media_player.alexa", "attributes": {"friendly_name": "Alexa"}}]
        return {"state": state["now"]}
    l.ha_get = fake_get
    l.ha_post = lambda url, payload: None
    l.open_home_assistant(focus="tv")
    check("with the token: Token says so and the TV is still to be chosen",
          l.ha_fields["token"].value.get_label() == l.t("ha_token_set")
          and l.ha_fields["tv"].value.get_label() == l.t("ha_tv_none"))
    l.press()


@step(400)
def tv6():
    l = L()
    top = l.overlays[-1]
    names = label_texts(top["backdrop"])
    check("the TV picker lists Home Assistant's media players", "TV da sala" in names and "Alexa" in names
          and len(top["rows"]) == 2)
    top["rows"][1][0].grab_focus()  # sorted by name: Alexa, TV da sala
    l.press()
    check("choosing one saves its entity and shows its name",
          l.cfg["home_assistant"]["tv_entity"] == "media_player.lg"
          and l.ha_fields["tv"].value.get_label() == "TV da sala")
    l.ha_fields["test"].grab_focus()
    l.press()


@step(400)
def tv7():
    l = L()
    check("the connection test also says whether the TV is on",
          l.t("ha_tv_is", state=l.t("ha_tv_off")) in label_texts(l.overlays[-1]["backdrop"]))
    while l.overlays:
        l.pop_overlay()
    from htpc.backends.base import GamepadEvent
    nav = l.navigator
    moved = []
    real_move, real_blocked = nav.move, nav.blocked
    nav.move = lambda dx, dy: moved.append((dx, dy))
    nav.blocked = lambda: True
    nav.handle(GamepadEvent("pad", "button", "right", 1))
    nav.handle(GamepadEvent("pad", "button", "right", 0))
    nav.handle(GamepadEvent("pad", "axis", "lx", 0.9))
    nav.handle(GamepadEvent("pad", "axis", "lx", 0.0))
    blocked_moves = list(moved)
    nav.blocked = lambda: False
    nav.handle(GamepadEvent("pad", "button", "right", 1))
    nav.handle(GamepadEvent("pad", "button", "right", 0))
    nav.move, nav.blocked = real_move, real_blocked
    check("TV off (gate closed): the launcher ignores the gamepad; on: it moves again",
          blocked_moves == [] and moved == [(1, 0)])
    del l.cfg["home_assistant"]
    l.tiles[0].grab_focus()


# ---------------- gamepad shortcuts ----------------

def hold(l, *buttons, value=1):
    from htpc.backends.base import GamepadEvent
    for b in buttons:
        l.navigator.handle(GamepadEvent("pad", "button", b, value))


@step(300)
def sc1():
    l = L()
    while l.overlays:
        l.pop_overlay()
    l.cfg.pop("shortcuts", None)
    l.hint.set_label(l.hint_text())
    check("the footer hint shows the default combos",
          "Home + LB + RB" in l.hint.get_label() and "Start + Select + LB + RB" in l.hint.get_label())
    l.RECORD_HOLD_MS = 150
    l.open_settings(focus="shortcuts")
    check("Settings has a gamepad shortcuts row", l.settings_fields["shortcuts"].value.get_label() == "Home + LB + RB")
    l.press()
    f = l.shortcut_fields
    check("it opens the shortcuts menu", list(f) == ["pairing", "home", "close", "volume", "reset"]
          and f["close"].value.get_label() == "Start + Select + LB + RB")
    f["home"].grab_focus()
    l.press()
    check("recording: the gamepad goes to the recorder", l.navigator.capture is not None)
    hold(l, "a")          # the release of the A that opened it, and a single button: not enough
    hold(l, "a", value=0)
    hold(l, "guide", "a")


@step(400)
def sc2():
    l = L()
    names = label_texts(l.overlays[-1]["backdrop"])
    check("holding Home + A records it and asks to confirm", l.navigator.capture is None
          and l.t("record_use", combo="Home + A") in names)
    hold(l, "guide", "a", value=0)
    l.press()   # Use
    check("saved: the home combo is now Home + A, and the hint says so",
          l.cfg["shortcuts"] == {"home": ["guide", "a"]} and l.shortcut_fields["home"].value.get_label() == "Home + A"
          and "Home + A" in l.hint.get_label())
    l.shortcut_fields["close"].grab_focus()
    l.press()
    hold(l, "start", "select")


@step(400)
def sc3():
    l = L()
    names = label_texts(l.overlays[-1]["backdrop"])
    check("a close combo that would overlap is refused", "Start + Select" in names
          and "Home + A" not in l.cfg["shortcuts"].get("close", []) and "close" not in l.cfg["shortcuts"])
    hold(l, "start", "select", value=0)
    l.pop_overlay()
    l.shortcut_fields["close"].grab_focus()
    l.press()
    hold(l, "b")


@step(400)
def sc4():
    l = L()
    screenshot(l.win, "16-shortcuts")
    check("holding B alone cancels the recording", l.navigator.capture is None
          and l.overlays[-1]["rows"][0][0] is not None and "close" not in l.cfg["shortcuts"])
    hold(l, "b", value=0)
    l.shortcut_fields["reset"].grab_focus()
    l.press()
    check("restore the defaults", "shortcuts" not in l.cfg and "Home + LB + RB" in l.hint.get_label())
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()


@step(300)
def vol1():
    l = L()
    from htpc.backends.base import GamepadEvent
    nav = l.navigator
    moved = []
    real_move = nav.move
    nav.move = lambda dx, dy: moved.append((dx, dy))
    for name, value in (("start", 1), ("select", 1), ("up", 1), ("up", 0), ("down", 1), ("down", 0),
                        ("start", 0), ("select", 0), ("down", 1), ("down", 0)):
        nav.handle(GamepadEvent("pad", "button", name, value))
    nav.move = real_move
    check("Start + Select + ↑/↓ (volume) does not move the selection; ↓ alone still does",
          moved == [(0, 1)])
    l.tiles[0].grab_focus()


# ---------------- the stylesheet ----------------

@step(100)
def css1():
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _p, section, error: errors.append(
        f"line {section.get_start_location().lines + 1}: {error.message}"))
    provider.load_from_path(os.path.join(ROOT, "launcher", "launcher.css"))
    check("launcher.css has no syntax GTK rejects (it would silently drop the rule)", errors == [])
    css = open(os.path.join(ROOT, "launcher", "launcher.css")).read()
    check("the selected tile's glow is not an endless animation (it kept the GPU busy while idle)",
          "tile-glow" in css and "tile-glow 3.2s ease-in-out 3;" in css
          and "tile-glow 1.6s ease-in-out infinite" not in css)


# ---------------- the launcher stops reading the gamepads behind an app ----------------

@step(300)
def bg1():
    l = L()
    nav = l.navigator
    if not nav.gamepads.available():
        check("gamepad polling stops behind an app (skipped: no evdev here)", True)
        return
    flushed = []
    real_flush = nav.gamepads.flush
    nav.gamepads.flush = lambda: flushed.append(True)
    nav.listen(True)
    reading = lambda: bool(nav.timer) or bool(nav.watches)   # a timer, or fds GLib waits on
    running = nav.listening and reading()
    nav.held["pad"] = "a"
    nav.listen(False)
    stopped = not nav.listening and not reading()
    nav.listen(True)
    check("behind an app the launcher stops reading the gamepads; back in front it drops what was "
          "pressed meanwhile and reads again",
          running and stopped and nav.listening and reading() and flushed and nav.held == {})
    fds = nav.gamepads.fds()
    check("with inotify the launcher waits on the gamepads' fds instead of polling every 16 ms",
          fds is None or (not nav.timer and set(nav.watches) == set(fds)))
    nav.gamepads.flush = real_flush


# ---------------- updates ----------------

@step(300)
def up1():
    l = L()
    from types import SimpleNamespace as NS
    while l.overlays:
        l.pop_overlay()
    l.updates_get = lambda url: [{"tag_name": "v9.0.0", "draft": False, "body": "", "html_url": "",
                                  "assets": [{"name": "h.tar.gz", "browser_download_url": "https://x/h.tar.gz"}]}]
    l.updates_run = lambda cmd, **kw: NS(returncode=0, stderr="",
                                         stdout="org.jellyfin.JellyfinDesktop\tJellyfin\n" if "--system" in cmd else "")
    l.open_settings()
    check("Settings has an Updates button next to Close the launcher",
          l.settings_updates in l.overlays[-1]["rows"][-1])
    l.settings_updates.grab_focus()
    l.press()


@step(600)
def up2():
    l = L()
    f = l.update_fields
    check("Updates: a newer launcher and the Flatpaks waiting are shown",
          f["launcher"].value.get_label() == l.t("updates_new", version="9.0.0")
          and f["flatpak"].value.get_label() == l.t("updates_apps", count=1))
    screenshot(l.win, "19-updates")
    installed = []
    import htpc.updates as up
    real = up.install_release
    up.install_release = lambda release, **kw: (installed.append(release["version"]),
                                                {"version": release["version"], "extension_changed": True})[1]
    l._real_install = real
    f["launcher"].grab_focus()
    l.press()                                   # asks first
    l.overlays[-1]["rows"][0][1].grab_focus()   # Install
    l.press()
    l._installed = installed


@step(600)
def up3():
    l = L()
    import htpc.updates as up
    up.install_release = l._real_install
    names = label_texts(l.overlays[-1]["backdrop"])
    check("installing: done, asks to restart the launcher and says the extension changed",
          l._installed == ["9.0.0"] and l.t("updates_installed", version="9.0.0") in names
          and l.t("updates_relogin") in names)
    l.pop_overlay()       # not now
    ran = []
    l.updates_run = lambda cmd, **kw: (ran.append(cmd[:2]), NS2(returncode=0, stdout="", stderr=""))[1]
    l.update_fields["flatpak"].grab_focus()
    l.press()
    l.overlays[-1]["rows"][0][1].grab_focus()
    l.press()
    l._ran = ran


@step(600)
def up4():
    l = L()
    check("updating the Flatpaks runs flatpak update and says they are up to date",
          ["flatpak", "update"] in l._ran and l.t("updates_apps_done") in label_texts(l.overlays[-1]["backdrop"])
          and l.update_fields["flatpak"].value.get_label() == l.t("updates_none"))
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()


# ---------------- per-app resolution (fake Mutter) ----------------

@step(300)
def disp1():
    l = L()
    import tempfile as _tf
    from htpc.backends.linux.display import MutterDisplay
    xml = pathlib.Path(_tf.mkdtemp()) / "monitors.xml"
    xml.write_text("<monitors version='2'><configuration><logicalmonitor><primary>yes</primary><monitor>"
                   "<monitorspec><connector>HDMI-2</connector></monitorspec><mode><width>2560</width>"
                   "<height>1440</height><rate>59.951</rate></mode></monitor></logicalmonitor>"
                   "</configuration></monitors>")
    l.display = MutterDisplay(monitors_xml=str(xml))
    fakes.mutter["current"] = "2560x1440@59.951"
    l.edit_app(0)
    check("edit mode has a Resolution field, Default when the app has none",
          l.field_display.value.get_label() == l.t("display_default"))
    l.field_display.grab_focus()
    l.press()


@step(400)
def disp2():
    l = L()
    top = l.overlays[-1]
    names = label_texts(top["backdrop"])
    check("the resolution list: Default (with the saved mode) and the screen's modes, biggest first",
          "2560×1440 · 60 Hz" in names and len(top["rows"]) == 1 + 6 - 0
          and "1024×768" not in names and "3840×2160 · 30 Hz" in names)
    screenshot(l.win, "18-resolution")
    top["rows"][1][0].grab_focus()     # 3840×2160 · 30 Hz
    l.press()


@step(300)
def disp3():
    l = L()
    check("chosen: the field shows it", l.field_display.value.get_label() == "3840×2160 · 30 Hz")
    l._save_app()
    app = l.cfg["apps"][0]
    check("saved as display_mode in apps.json", app.get("display_mode") == "3840x2160@30")
    changed = l.use_display_mode(app["display_mode"])
    check("opening the app switches the screen to its mode", changed and fakes.mutter["current"] == "3840x2160@30.000"
          and fakes.mutter["applied"][-1][0] == 1)
    check("already there: nothing to do", l.use_display_mode(app["display_mode"]) is False)
    l.display_changed = True
    l.display_app_until = 0
    l.restore_display()
    check("back in the launcher: the default again", fakes.mutter["current"] == "2560x1440@59.951")
    l.edit_app(0)
    l._display_chosen(None)
    l._save_app()
    check("Default removes it from apps.json", "display_mode" not in l.cfg["apps"][0])
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()


# ---------------- audio output ----------------

@step(300)
def au1():
    l = L()
    from htpc.backends.linux.audio import PulseAudio
    state = {"default": "alsa_output.hdmi"}
    sinks = [{"name": "alsa_output.hdmi", "description": "TV (HDMI)", "properties": {}},
             {"name": "bluez_output.X.1", "description": "JBL Flip 5", "properties": {"device.bus": "bluetooth"}}]

    def run(cmd):
        if cmd[1:] == ["-f", "json", "list", "sinks"]:
            return json.dumps(sinks)
        if cmd[1] == "get-default-sink":
            return state["default"]
        if cmd[1] == "set-default-sink":
            state["default"] = cmd[2]
        return ""
    l.audio = PulseAudio(run=run)
    l._audio_state = state
    while l.overlays:
        l.pop_overlay()
    l.open_settings(focus="audio")
    l.press()


@step(500)
def au2():
    l = L()
    a = l.audio_menu
    names = label_texts(a["listing"])
    check("Settings → Audio lists the outputs, the one in use marked and focused",
          "TV (HDMI)" in names and "JBL Flip 5" in names and l.t("audio_current") in names
          and l.win.get_focus() is a["rows"][0][0] and a["rows"][-2] == [a["pair"]])
    check("Settings shows the output in use", l.settings_fields["audio"].value.get_label() == "TV (HDMI)")
    screenshot(l.win, "20-audio")
    a["rows"][1][0].grab_focus()
    l.press()


@step(500)
def au3():
    l = L()
    a = l.audio_menu
    check("choosing the speaker sends the sound there", l._audio_state["default"] == "bluez_output.X.1"
          and a["rows"][0][0].audio_id == "bluez_output.X.1"
          and a["rows"][0][0].value.get_label() == l.t("audio_current"))
    from htpc.backends.linux.bluetooth import BluezBluetooth
    fakes.bluez["devices"].clear()
    fakes.bluez["fail_pair"].clear()
    fakes.bluez["adapter"].update(Powered=False, Discovering=False)
    l.bluetooth = BluezBluetooth(bus="SESSION", sysfs=None)
    l.PAIRING_REFRESH_MS = 200
    a["pair"].grab_focus()
    l.press()


@step(900)
def au4():
    l = L()
    names = label_texts(l.overlays[-1]["backdrop"])
    check("'Pair headphones or a speaker' lists audio devices, not gamepads",
          l.t("pairing_audio_title") in names and "JBL Speaker" in names and "Xbox" not in names)
    l.back()
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()


# ---------------- pairing gamepads (fake BlueZ) ----------------

@step(300)
def bt1():
    l = L()
    from htpc.backends.base import Bluetooth
    while l.overlays:
        l.pop_overlay()
    l.bluetooth = Bluetooth()   # no adapter
    l.open_shortcuts(focus="pairing")
    check("Settings → Gamepads starts with 'Pair a gamepad'", list(l.shortcut_fields)[0] == "pairing")
    l.press()


@step(400)
def bt2():
    l = L()
    check("without an adapter it says what to do instead",
          l.t("pairing_no_adapter") in label_texts(l.overlays[-1]["backdrop"]))
    l.pop_overlay()
    from htpc.backends.linux.bluetooth import BluezBluetooth
    fakes.bluez["devices"].clear()
    fakes.bluez["fail_pair"].clear()
    fakes.bluez["adapter"].update(Powered=False, Discovering=False)
    l.bluetooth = BluezBluetooth(bus="SESSION", sysfs=None)
    l.PAIRING_REFRESH_MS = 200
    l.shortcut_fields["pairing"].grab_focus()
    l.press()


@step(900)
def bt3():
    l = L()
    names = label_texts(l.overlays[-1]["backdrop"])
    check("with an adapter: it searches and lists only gamepads with a name",
          fakes.bluez["adapter"]["Discovering"] and "Xbox Wireless Controller" in names
          and "Wireless Controller" in names and "JBL" not in names and "CC-CC" not in names)
    screenshot(l.win, "17-pairing")
    rows = l.pairing["rows"]
    check("keyboards and mice are listed too, with their kind",
          "Logitech K380  ·  " + l.t("bt_kind_keyboard") in names and "MX Anywhere 3  ·  " + l.t("bt_kind_mouse") in names)
    check("the devices are navigable rows, Close last", len(rows) == 5 and rows[-1][0] is l.pairing["close"])
    target = next(r[0] for r in rows if getattr(r[0], "bt_address", "") == "AA:AA:AA:AA:AA:AA")
    target.grab_focus()
    l.press()


@step(900)
def bt4():
    l = L()
    check("pairing a gamepad: paired, trusted, connected, and it says so",
          fakes.bluez["devices"]["AA:AA:AA:AA:AA:AA"].get("Trusted")
          and l.t("pairing_done", name="Xbox Wireless Controller") in label_texts(l.overlays[-1]["backdrop"]))
    l.pop_overlay()


@step(700)
def bt5():
    l = L()
    row = next(r[0] for r in l.pairing["rows"] if getattr(r[0], "bt_address", "") == "AA:AA:AA:AA:AA:AA")
    check("the list now shows it as connected", row.value.get_label() == l.t("pairing_connected"))
    fakes.bluez["fail_pair"].add("DD:DD:DD:DD:DD:DD")
    next(r[0] for r in l.pairing["rows"] if getattr(r[0], "bt_address", "") == "DD:DD:DD:DD:DD:DD").grab_focus()
    l.press()


@step(900)
def bt6():
    l = L()
    check("a failed pairing says so", "Wireless Controller" in label_texts(l.overlays[-1]["backdrop"])
          and not fakes.bluez["devices"]["DD:DD:DD:DD:DD:DD"].get("Paired"))
    l.pop_overlay()
    row = next(r[0] for r in l.pairing["rows"] if getattr(r[0], "bt_address", "") == "AA:AA:AA:AA:AA:AA")
    row.grab_focus()
    l.press()       # a paired one: asks to forget it
    l.overlays[-1]["rows"][0][1].grab_focus()
    l.press()       # Forget


@step(700)
def bt7():
    l = L()
    check("forgetting removes it", "AA:AA:AA:AA:AA:AA" not in fakes.bluez["devices"])
    l.back()        # B closes the pairing screen
    check("closing the screen stops the search", l.pairing is None)


@step(500)
def bt8():
    l = L()
    check("discovery is off after closing", fakes.bluez["adapter"]["Discovering"] is False)
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()

# ---------------- home screen: recently added (Jellyfin) and the house (Home Assistant) ----------------

def png(rgb):
    from gi.repository import Gdk as _Gdk
    tex = _Gdk.MemoryTexture.new(4, 4, _Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(bytes([*rgb, 255]) * 16), 16)
    return tex.save_to_png_bytes().get_data()


JF_LATEST = [
    {"Id": "m1", "Type": "Movie", "Name": "Filme Um", "ProductionYear": 2024, "RunTimeTicks": 112 * 600_000_000,
     "ImageTags": {"Primary": "p"}, "BackdropImageTags": ["b"]},
    {"Id": "s1", "Type": "Series", "Name": "Série Dois", "ChildCount": 3, "ImageTags": {"Primary": "p"}},
    {"Id": "e1", "Type": "Episode", "Name": "Piloto", "SeriesName": "Série Três", "SeriesId": "s3",
     "SeriesPrimaryImageTag": "p", "ParentIndexNumber": 1, "IndexNumber": 2},
]
HA_STATES = [
    {"entity_id": "light.sala", "state": "on",
     "attributes": {"friendly_name": "Luz do teto", "brightness": 204, "supported_color_modes": ["brightness"]}},
    {"entity_id": "light.abajur", "state": "off", "attributes": {"friendly_name": "Abajur", "supported_color_modes": ["onoff"]}},
    {"entity_id": "switch.som", "state": "on", "attributes": {"friendly_name": "Tomada do som"}},
    {"entity_id": "scene.cinema", "state": "x", "attributes": {"friendly_name": "Modo cinema"}},
    {"entity_id": "media_player.tv", "state": "on", "attributes": {"friendly_name": "TV"}},
]


JF_LIBRARY = {"Items": [
    {"Id": "lib1", "Type": "Movie", "Name": "Filme em Alta", "ProviderIds": {"Tmdb": "77"}, "ImageTags": {"Primary": "p"},
     "BackdropImageTags": ["b"], "ProductionYear": 2025},
    {"Id": "lib2", "Type": "Series", "Name": "Série em Alta", "ProviderIds": {"Tmdb": "88"}, "ImageTags": {"Primary": "p"}},
    {"Id": "lib3", "Type": "Movie", "Name": "Fora da lista", "ProviderIds": {"Tmdb": "5"}},
]}


def jf_get(url, key):
    import urllib.parse as up
    state.setdefault("jf_calls", []).append(url)
    parts = up.urlsplit(url)
    path, query = parts.path, dict(up.parse_qsl(parts.query))
    if path == "/Users":
        return json.dumps([{"Id": "u1", "Name": "mu", "Policy": {"IsAdministrator": True}}]).encode()
    if path.endswith("/Items/Latest"):
        types = query.get("IncludeItemTypes", "")
        items = [i for i in JF_LATEST if types != "Movie" or i["Type"] == "Movie"]
        items = [i for i in items if types != "Episode,Series" or i["Type"] != "Movie"]
        return json.dumps(items).encode()
    if path.endswith("/Items"):
        return json.dumps(JF_LIBRARY).encode()
    if path == "/System/Info":
        return json.dumps({"ServerName": "servidor", "Version": "10.11.0"}).encode()
    return png((200, 120, 60))


def ha_states(url, token):
    return HA_STATES


def ha_api_post(url, token, payload):
    state.setdefault("ha_posts", []).append((url.split("/api/", 1)[1], payload))
    if url.endswith("/template"):
        return json.dumps({"light.sala": "Sala", "light.abajur": "Quarto", "switch.som": "Sala"})
    return "[]"


@step(300)
def h1():
    l = L()
    while l.overlays:
        l.pop_overlay()
    check("not set up: no Recently added and no house; the apps are alone, in the middle",
          not l.recent_section.get_visible() and not l.house_section.get_visible() and l.grid.get_vexpand())
    l.jellyfin_get, l.ha_get, l.ha_api_post = jf_get, ha_states, ha_api_post
    l.cfg["jellyfin"] = {"url": "http://jf:8096", "api_key": "k"}
    ha = dict(l.cfg.get("home_assistant") or {})
    ha.update(url="http://192.168.0.22:8123", token="T")
    ha.pop("devices", None)
    ha.pop("home_screen", None)
    l.cfg["home_assistant"] = ha
    l.tiles[1].grab_focus()
    l.tiles[0].grab_focus()   # Jellyfin in focus: its row shows
    l.update_recent(force=True)
    l.update_house()


@step(900)
def h2():
    l = L()
    check("Recently added shows Jellyfin's newest, the first one wide",
          l.recent_section.get_visible() and [c.item["title"] for c in l.recent_cards] == ["Filme Um", "Série Dois", "Série Três"]
          and l.recent_cards[0].has_css_class("wide"))
    check("their pictures arrive", all(c.picture.get_paintable() is not None for c in l.recent_cards))
    check("the house shows every light by room, plus the scenes",
          l.house_section.get_visible() and [t.device["entity"] for t in l.device_tiles] == ["light.abajur", "light.sala"]
          and [b.scene["entity"] for b in l.scene_buttons] == ["scene.cinema"]
          and l.device_tiles[1].state.get_label() == l.t("dev_brightness", pct=80) and l.device_tiles[1].has_css_class("on"))
    check("rows: top buttons, the tabs, their row, apps, scenes, lights",
          l.rows[0] == l.top_buttons and l.rows[1] == l.tab_row and l.rows[2] == l.recent_cards
          and l.rows[3] == l.tiles and l.rows[4] == l.scene_buttons and l.rows[5] == l.device_tiles)
    check("without a TMDB key and without Steam: Explore, Series and Films; Explore shows what's new",
          [b.tab for b in l.tab_row] == ["explore", "series", "movies"] and l.media_tab == "explore"
          and l.media_note.get_label() == l.t("explore_note_no_tmdb"))
    check("with other rows, the apps sit at the top of their space", not l.grid.get_vexpand())
    l.tiles[0].grab_focus()
    l.move(0, -1)
    check("up from the apps reaches Recently added", l.win.get_focus() in l.recent_cards)
    screenshot(l.win, "30-home-recently-added")
    l.move(0, 1)
    l.move(0, 1)
    check("down from the apps reaches the scenes, the apps dim and the screen scrolls",
          l.win.get_focus() in l.scene_buttons and l.grid.has_css_class("dimmed")
          and l.scroller.get_vadjustment().get_value() > 0)
    l.move(0, 1)
    l.move(1, 0)
    check("then the lights", l.win.get_focus() is l.device_tiles[1])


@step(300)
def h2b():
    l = L()
    screenshot(l.win, "31-home-house")
    state["ha_posts"] = []
    l.press()
    check("Ⓐ turns the light off at once", not l.device_tiles[1].has_css_class("on"))


@step(300)
def h3():
    l = L()
    check("...and asks Home Assistant to", ("services/light/toggle", {"entity_id": "light.sala"}) in state["ha_posts"])
    l.device_tiles[1].grab_focus()
    l.device_tiles[1].update(HA_STATES and l.device_tiles[1].device | {"on": True, "brightness": 80})
    l.other_button("y")
    check("Ⓨ on a dimmable light opens its brightness", len(l.overlays) == 1 and l.brightness_value.get_label() == "80%")
    state["ha_posts"] = []
    l.press()   # focus starts on +
    check("+ raises it by 10 %", l.brightness_value.get_label() == "90%")


@step(300)
def h3b():
    l = L()
    screenshot(l.win, "32-brightness")
    l.back()
    l.device_tiles[0].grab_focus()
    l.other_button("y")
    check("Ⓨ on an on/off light does nothing", not l.overlays)


@step(500)
def h4():
    l = L()
    check("the brightness went to Home Assistant",
          ("services/light/turn_on", {"entity_id": "light.sala", "brightness_pct": 90}) in state["ha_posts"])
    l.move(0, -1)
    l.move(0, -1)
    check("back up to the apps: not dimmed, scrolled back to the top",
          l.win.get_focus() in l.tiles and not l.grid.has_css_class("dimmed")
          and l.scroller.get_vadjustment().get_value() == 0)
    opened = []
    real = l.open_app
    l.open_app = lambda tile: opened.append(tile.app["id"])
    l.recent_cards[1].grab_focus()
    l.press()
    l.open_app = real
    check("a Recently added card opens the Jellyfin app", opened == ["org.jellyfin.JellyfinDesktop"])
    l.open_settings(focus="jellyfin")
    check("Settings has a Jellyfin row", l.settings_fields["jellyfin"].value.get_label() == "jf:8096")
    l.press()
    f = l.jf_fields
    check("it opens the Jellyfin menu", list(f) == ["enabled", "url", "key", "user", "tmdb", "test"]
          and f["key"].value.get_label() == l.t("jf_key_set") and f["user"].value.get_label() == l.t("jf_user_auto"))



@step(300)
def h4b():
    l = L()
    screenshot(l.win, "33-settings-jellyfin")
    l.jf_fields["test"].grab_focus()
    l.press()


@step(500)
def h5():
    l = L()
    check("the test says where it connected", l.t("jf_test_ok", server="servidor", version="10.11.0", count=3)
          in label_texts(l.overlays[-1]["backdrop"]))
    while l.overlays:
        l.pop_overlay()
    l.open_home_assistant(focus="home")
    check("Home Assistant → Lights on the home screen: all lights", l.ha_fields["home"].value.get_label() == l.t("ha_home_all"))
    l.press()


@step(500)
def h6():
    l = L()
    f = l.ha_home_fields
    check("the list has every light and switch, the lights ticked",
          [b.entity for b in f["items"]] == ["light.abajur", "light.sala", "switch.som"]
          and [b.value.get_label() for b in f["items"]] == ["✓", "✓", ""])


@step(300)
def h6b():
    l = L()
    f = l.ha_home_fields
    screenshot(l.win, "34-home-lights-choice")
    f["items"][2].grab_focus()
    l.press()
    check("ticking the switch saves a choice", l.cfg["home_assistant"]["devices"] == ["light.abajur", "light.sala", "switch.som"]
          and l.ha_fields["home"].value.get_label() == l.t("ha_home_some", n=3))
    f["items"][0].grab_focus()
    l.press()
    check("unticking a light keeps the others", l.cfg["home_assistant"]["devices"] == ["light.sala", "switch.som"])


@step(700)
def h7():
    l = L()
    check("the house follows the choice, in its order",
          [t.device["entity"] for t in l.device_tiles] == ["light.sala", "switch.som"])
    l.ha_home_fields["show"].grab_focus()
    l.press()
    check("'Show under the apps' off is saved", l.cfg["home_assistant"]["home_screen"] is False)
    while l.overlays:
        l.pop_overlay()
    l.cfg["jellyfin"]["enabled"] = False
    l.update_recent(force=True)


@step(500)
def h8():
    l = L()
    check("both switched off: the rows go away and the apps are alone again",
          not l.recent_section.get_visible() and not l.house_section.get_visible() and l.grid.get_vexpand()
          and l.rows[1] == [] and l.house_rows == [])
    l.cfg.pop("jellyfin", None)
    l.cfg["home_assistant"].pop("devices", None)
    l.cfg["home_assistant"].pop("home_screen", None)
    l.cfg["home_assistant"].pop("token", None)
    l.save_config()
    l.tiles[0].grab_focus()


# ---------------- media tabs: Explore (TMDB × Jellyfin), Series, Films, Games (Steam) ----------------

def tmdb_get(url, headers):
    import urllib.parse as up
    path = up.urlsplit(url).path
    if path == "/3/trending/movie/week":
        return {"results": [{"id": 1}, {"id": 77}]}
    if path == "/3/trending/tv/week":
        return {"results": [{"id": 88}]}
    if path == "/3/trending/all/week":
        return {"results": [{"id": 1}] * 20}
    return {"results": []}


def fake_steam(home):
    import time as _time
    root = pathlib.Path(home) / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    (root / "steamapps").mkdir(parents=True, exist_ok=True)
    (root / "userdata/1/config").mkdir(parents=True, exist_ok=True)
    now = int(_time.time())
    (root / "userdata/1/config/localconfig.vdf").write_text(
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { '
        f'"620" {{ "LastPlayed" "{now - 3600}" "Playtime" "300" }} '
        f'"440" {{ "LastPlayed" "{now - 3 * 86400}" }} '
        f'"730" {{ "LastPlayed" "{now - 2 * 86400}" "Playtime" "90" }} }} }} }} }} }}')
    for appid, name in (("620", "Portal 2"), ("440", "Team Fortress 2")):
        (root / f"steamapps/appmanifest_{appid}.acf").write_text(f'"AppState" {{ "appid" "{appid}" "name" "{name}" }}')
    cache = root / "appcache/librarycache/620"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "library_600x900.jpg").write_bytes(png((60, 120, 200)))


@step(300)
def m1():
    l = L()
    while l.overlays:
        l.pop_overlay()
    steam_home = tempfile.mkdtemp()
    fake_steam(steam_home)
    l.steam_home_dir = steam_home
    from htpc import steam as _steam
    l.steam_names = _steam.Names(pathlib.Path(steam_home) / "names.json",
                                 lambda appid: ("Jogo Por Streaming", "game") if appid == "730" else None)
    l.steam_image_get = lambda url: state.setdefault("steam_cdn", []).append(url) or png((200, 60, 60))
    l.jellyfin_get, l.tmdb_get = jf_get, tmdb_get
    l.cfg["jellyfin"] = {"url": "http://jf:8096", "api_key": "k"}
    l.cfg["tmdb"] = {"api_key": "a" * 32}
    l.media_tab = "explore"
    l.update_media(force=True)


@step(900)
def m2():
    l = L()
    check("Jellyfin in focus: Explore, Series and Films (no Games)",
          l.media_context == "jellyfin" and [b.tab for b in l.tab_row] == ["explore", "series", "movies"])
    check("Explore: TMDB's popular titles that are in the library, in TMDB's order",
          [c.item["title"] for c in l.recent_cards] == ["Série em Alta", "Filme em Alta"]
          and l.media_note.get_label() == l.t("explore_note")
          and l.recent_cards[0].get_child().get_last_child().get_first_child().get_label() == l.t("media_kind_hot_series"))
    l.move(0, -1)
    l.move(0, -1)
    check("up from Jellyfin reaches the tabs", l.win.get_focus() in l.tab_row)
    l.tab_buttons["explore"].grab_focus()
    l.move(1, 0)
    check("moving onto Series shows the series", l.media_tab == "series"
          and [c.item["title"] for c in l.recent_cards] == ["Série Dois", "Série Três"])
    l.move(1, 0)
    l.move(1, 0)
    check("Films shows the films, and is the last tab", l.win.get_focus() is l.tab_buttons["movies"]
          and [c.item["title"] for c in l.recent_cards] == ["Filme Um"])
    moonlight = next(t for t in l.tiles if "moonlight" in t.app["id"].lower())
    moonlight.grab_focus()
    check("an app without a row: no tabs and no cards, the space stays",
          l.media_context is None and l.tab_row == [] and l.recent_cards == [] and l.recent_section.get_visible())
    steam_tile = next(t for t in l.tiles if "steam" in t.app["id"].lower())
    steam_tile.grab_focus()
    check("Steam in focus: only Games, last played first, streamed ones (named by the store) too",
          [b.tab for b in l.tab_row] == ["games"] and l.media_note.get_label() == l.t("games_note")
          and [c.item["title"] for c in l.recent_cards] == ["Portal 2", "Jogo Por Streaming", "Team Fortress 2"])


@step(500)
def m3():
    l = L()
    screenshot(l.win, "35-games-with-steam-in-focus")
    check("the game's cover comes from Steam's own cache", l.recent_cards[0].picture.get_paintable() is not None)
    spawned = []
    real = l._spawn
    l._spawn = lambda command: spawned.append(command) or True
    l.move(0, -1)
    check("up from Steam reaches its games", l.win.get_focus() in l.recent_cards)
    l.recent_cards[0].grab_focus()
    l.press()
    l._spawn = real
    steam_app = next(t.app for t in l.tiles if "steam" in t.app["id"].lower())
    check("a game starts through the same Steam shortcut", spawned and spawned[0][-1] == "steam://rungameid/620"
          and spawned[0][0] == steam_app["launch"][0])
    check("a streamed game's cover comes from Steam's image servers",
          any("/apps/730/" in u for u in state.get("steam_cdn", [])) and l.recent_cards[1].picture.get_paintable() is not None)
    l.recent_cards[1].grab_focus()
    l._spawn = lambda command: spawned.append(command) or True
    l.press()
    l._spawn = real
    check("a streamed game opens its Steam page (where Stream is)", spawned[-1][-1] == "steam://nav/games/details/730")
    # Pages: twelve films, five a page
    from htpc.backends.base import GamepadEvent as E
    nav = l.navigator
    nav.active = lambda: True
    l.tiles[0].grab_focus()
    l.select_tab("movies")
    l.media["movies"] = [{"id": f"f{n}", "kind": "movie", "title": f"Filme {n}"} for n in range(12)]
    l.media_page["movies"] = 0
    l._show_media()
    check("five cards a page, and the note says which page", [c.item["title"] for c in l.recent_cards]
          == [f"Filme {n}" for n in range(5)] and l.media_note.get_label().endswith(l.t("media_pages", page=1, pages=3)))
    nav.handle(E("pad", "button", "r1", 1)); nav.handle(E("pad", "button", "r1", 0))
    check("RB: the next five, with Jellyfin still in focus", [c.item["title"] for c in l.recent_cards]
          == [f"Filme {n}" for n in range(5, 10)] and l.win.get_focus() is l.tiles[0])
    nav.handle(E("pad", "button", "r1", 1)); nav.handle(E("pad", "button", "r1", 0))
    nav.handle(E("pad", "button", "r1", 1)); nav.handle(E("pad", "button", "r1", 0))
    check("RB on the last page stays there", [c.item["title"] for c in l.recent_cards] == ["Filme 10", "Filme 11"])
    nav.handle(E("pad", "button", "l1", 1)); nav.handle(E("pad", "button", "l1", 0))
    check("LB goes back", l.recent_cards[0].item["title"] == "Filme 5")
    nav.handle(E("pad", "button", "guide", 1)); nav.handle(E("pad", "button", "l1", 1))
    nav.handle(E("pad", "button", "r1", 1))
    for b in ("r1", "l1", "guide"):
        nav.handle(E("pad", "button", b, 0))
    check("Home + LB + RB (back to the launcher) does not turn the page", l.recent_cards[0].item["title"] == "Filme 5")
    nav.handle(E("pad", "button", "l1", 1)); nav.handle(E("pad", "button", "r1", 1))
    nav.handle(E("pad", "button", "l1", 0)); nav.handle(E("pad", "button", "r1", 0))
    check("nor do LB and RB together", l.recent_cards[0].item["title"] == "Filme 5")
    l.recent_cards[2].grab_focus()
    l.page_media(-1)
    check("turning the page with a card in focus keeps the focus in the row", l.win.get_focus() is l.recent_cards[2]
          and l.recent_cards[0].item["title"] == "Filme 0")
    l.tiles[0].grab_focus()


@step(300)
def m4():
    l = L()
    screenshot(l.win, "36-films-page-1")
    l.cfg.pop("jellyfin", None)
    l.cfg.pop("tmdb", None)
    l.steam_home_dir = tempfile.mkdtemp()
    l.update_media(force=True)
    check("nothing set up: no tabs", not l.recent_section.get_visible() and l.tab_row == [])
    l.save_config()
    l.tiles[0].grab_focus()


@step(200)
def finish():
    L().win.get_application().quit()


def schedule():
    total = 0
    for delay, f in steps:
        total += delay
        GLib.timeout_add(total, lambda f=f: (f(), False)[1])


GLib.idle_add(lambda: (schedule(), False)[1])
sys.argv = ["launcher.py"]
launcher.main()
print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
