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
    orig_init(self, app)
    state["l"] = self


launcher.Launcher.__init__ = init
launcher.RESUME_DELAY = 300

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
    before = dict(l.opening)
    l.press()
    check("pressing again while it opens does not start another", l.opening == before)


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
    check("the gear enters edit mode", l.editing and l.add_tile is not None)
    check("the hint switches to edit mode", "Modo de edição" in l.hint.get_label())
    check("the button becomes 'Concluir'", l.btn_settings.label.get_label() == "Concluir")


@step(300)
def b1():
    l = L()
    check("the Background button only shows in edit mode", l.btn_background.get_visible() and l.btn_background in l.rows[-1])
    l.btn_background.grab_focus()
    l.press()
    swatches = [b for row in l.overlays[-1]["rows"] for b in row]
    check("the background picker offers 9 colors", len(swatches) == 9)
    check("focus starts on the current color", l.win.get_focus() is swatches[0] and l.theme == "midnight")
    l.move(1, 0)
    check("moving the focus previews the color", l.theme == "ocean")
    l.back()
    check("Ⓑ goes back to the saved color", l.theme == "midnight" and not l.overlays)


@step(300)
def b2():
    l = L()
    l.press()
    l.move(0, 1)  # second row, first column: aurora
    l.press()
    saved = json.load(open(f"{cfgdir}/htpc-launcher/apps.json"))
    check("Ⓐ keeps the color and saves it to apps.json", l.theme == "aurora" and saved.get("background") == "aurora" and not l.overlays)


@step(500)
def b3():
    screenshot(L().win, "5b-background-aurora")
    L().press()


@step(500)
def b4():
    l = L()
    screenshot(l.win, "5c-background-picker")
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
    check("Ⓑ leaves edit mode", not l.editing and l.add_tile is None and l.btn_settings.label.get_label() == "Editar apps")
    check("the Background button hides again", not l.btn_background.get_visible())


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
    l.gamepads.connected = lambda: ["Xbox", "8BitDo"]
    l._update_gamepads()
    l.tiles[0].grab_focus()


@step(300)
def n2():
    l = L()
    screenshot(l.win, "9-two-gamepads")
    l.gamepads.connected = lambda: []
    l._update_gamepads()


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
