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
    tex = win.get_native().get_renderer().render_texture(snap.to_node(), None)
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
    check("down goes to the footer (closest button)", l.win.get_focus() in (l.btn_settings, l.btn_restart, l.btn_power))
    l.move(-1, 0)
    for _ in range(3):
        l.move(1, 0)
    check("right in the footer reaches Shut down", l.win.get_focus() is l.btn_power)


@step(400)
def s4b():
    screenshot(L().win, "2-power-focused")


@step(100)
def s5():
    l = L()
    l.press()
    check("Shut down asks for confirmation", len(l.overlays) == 1)
    check("default focus is Cancel", l.win.get_focus() is l.overlays[-1]["rows"][0][0])
    l.move(0, 1)
    check("down inside the dialog stays in the dialog", l.win.get_focus() in l.overlays[-1]["rows"][0])


@step(400)
def s6():
    l = L()
    screenshot(l.win, "3-confirm-power-off")
    l.back()
    check("B closes the confirmation", not l.overlays)
    check("focus returns to Shut down", l.win.get_focus() is l.btn_power)
    l.move(0, -1)
    check("up goes back to the apps", l.win.get_focus() in l.tiles)
    l.move(0, -1)
    check("up from the apps stays on the apps", l.win.get_focus() in l.tiles)


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
    l.tiles[-1].grab_focus()
    l.move(0, 1)
    check("down from the last app reaches the footer", l.win.get_focus() in (l.btn_settings, l.btn_restart, l.btn_power))
    l.btn_settings.grab_focus()
    l.press()
    f = l.settings_fields
    check("the gear opens Settings with apps, background, location, temperature and language",
          len(l.overlays) == 1 and list(f) == ["apps", "background", "location", "unit", "language", "notifications"])
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
    l.overlays[-1]["rows"][3][0].grab_focus()
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
    l.overlays[-1]["rows"][3][0].grab_focus()
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
    l.overlays[-1]["rows"][3][0].grab_focus()
    l.press()
    check("the new app goes to the end of the list", saved_apps()[-1]["id"] == "org.example.Player" and len(l.tiles) == 5)
    check("with 5 apps + Add, the grid wraps onto 2 rows", len(l.tile_rows) == 2)


@step(500)
def e8():
    l = L()
    screenshot(l.win, "10-five-apps")
    l.tiles[0].grab_focus()
    l.press()
    remove = l.overlays[-1]["rows"][3][1]
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
    nav.handle(E("pad", "button", "down", 1)); nav.handle(E("pad", "button", "down", 0))
    check("gamepad: d-pad down reaches the footer", l.win.get_focus() in l.rows[-1])
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


# ---------------- "Turn off TV" (Home Assistant) ----------------

@step(300)
def tv1():
    l = L()
    while l.overlays:
        l.pop_overlay()
    check("no Home Assistant set up: no 'Desligar TV' button", not l.btn_tv.get_visible()
          and l.btn_tv not in l.rows[-1])
    l.cfg["home_assistant"] = {"url": "http://ha.local:8123", "webhook_id": "htpc-test"}
    l.build_ui()
    l.refresh_top_bar()
    l.btn_tv.grab_focus()


@step(500)
def tv2():
    l = L()
    from htpc import home_assistant as hass
    ok, r = l.btn_tv.compute_bounds(l.win)
    middle = r.get_x() + r.get_width() / 2
    check("with Home Assistant: 'Desligar TV' in the middle of the footer",
          l.btn_tv.get_visible() and abs(middle - l.win.get_width() / 2) < 4
          and l.btn_tv.label.get_label() == l.t("tv_off") and l.rows[-1][0] is l.btn_tv)
    screenshot(l.win, "15-tv-off-button")
    posted = []
    real = hass.http_post
    hass.http_post = lambda url, payload: posted.append((url, payload["event"]))
    l.press()


@step(400)
def tv3():
    l = L()
    from htpc import home_assistant as hass
    check("'Desligar TV' sends tv_off to the Home Assistant webhook and leaves the marker",
          hass.tv_off_marker().exists())
    del l.cfg["home_assistant"]
    l.build_ui()
    l.refresh_top_bar()
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
