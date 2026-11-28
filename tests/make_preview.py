# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Draws the screenshots for the README and the release page (docs/*.png).

Everything on them is made up here: the films and series (invented titles, abstract
pictures), the apps' icons (plain shapes, no third-party logos), the lights, the weather.

Run: xvfb-run -a -s "-screen 0 1920x1080x24" dbus-run-session -- python3 tests/make_preview.py [out-dir]
The pictures go to out-dir (default: docs/).
"""
import datetime
import json
import math
import os
import random
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.join(ROOT, "launcher"))
sys.path.insert(0, os.path.dirname(__file__))

home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["XDG_CONFIG_HOME"] = f"{home}/.config"
os.environ["XDG_DATA_HOME"] = f"{home}/.local/share"
os.environ["XDG_CACHE_HOME"] = f"{home}/.cache"
icons = f"{home}/.local/share/htpc-launcher/app-icons"
os.makedirs(icons)
os.makedirs(f"{home}/.config/htpc-launcher")


# ---------------- made-up pictures ----------------

def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def art(seed, w, h):
    """An abstract scene: a sky, a sun or moon, layered hills. Same seed, same picture."""
    r = random.Random(seed)
    palettes = [((24, 32, 74), (232, 120, 90)), ((10, 40, 60), (90, 200, 190)), ((40, 16, 60), (240, 170, 90)),
                ((12, 22, 40), (120, 140, 220)), ((60, 20, 30), (250, 200, 140)), ((14, 50, 36), (200, 230, 150))]
    top, bottom = palettes[seed % len(palettes)]
    img = gradient(w, h, top, bottom)
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy, rad = r.uniform(0.2, 0.8) * w, r.uniform(0.18, 0.42) * h, r.uniform(0.06, 0.12) * max(w, h)
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(255, 240, 210, 220))
    for layer in range(4):
        base = h * (0.55 + layer * 0.12)
        shade = tuple(int(c * (0.75 - layer * 0.17)) for c in top)
        pts = [(0, h)]
        phase, amp, freq = r.uniform(0, 6.3), h * r.uniform(0.04, 0.09), r.uniform(1.5, 3.5)
        for x in range(0, w + 8, 8):
            pts.append((x, base + amp * math.sin(phase + freq * x / w * math.pi)))
        pts.append((w, h))
        d.polygon(pts, fill=(*shade, 255))
    return img.filter(ImageFilter.GaussianBlur(0.6))


def save_png(img):
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def icon(path, color, shape):
    """A plain app icon: a rounded square with a simple white shape."""
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, s - 8, s - 8], 56, fill=color)
    w = (255, 255, 255, 255)
    if shape == "play":
        d.polygon([(100, 78), (100, 178), (182, 128)], fill=w)
    elif shape == "rings":
        d.ellipse([64, 64, 192, 192], outline=w, width=18)
        d.ellipse([104, 104, 152, 152], fill=w)
    elif shape == "stream":
        d.rounded_rectangle([56, 70, 200, 160], 14, outline=w, width=16)
        d.rectangle([108, 160, 148, 188], fill=w)
        d.rounded_rectangle([84, 184, 172, 200], 6, fill=w)
    elif shape == "dots":
        for x, y in ((88, 100), (168, 100), (128, 160)):
            d.ellipse([x - 26, y - 26, x + 26, y + 26], fill=w)
        d.line([(88, 100), (168, 100), (128, 160), (88, 100)], fill=w, width=10)
    img.save(path)


for name, color, shape in (("video", (205, 60, 60), "play"), ("media", (110, 80, 200), "rings"),
                           ("stream", (40, 120, 190), "stream"), ("games", (40, 60, 90), "dots")):
    icon(f"{icons}/{name}.png", color, shape)

# ---------------- made-up library ----------------

TITLES = [("Movie", "The Northern Light", 2025, 118), ("Series", "Aurora Station", 2025, None),
          ("Movie", "Sand Roads", 2025, 104), ("Series", "Keepers of the Valley", 2024, None),
          ("Movie", "Last Summer Days", 2025, 97), ("Series", "Open Sea", 2025, None),
          ("Movie", "Glass City", 2025, 126), ("Series", "Lisbon Nights", 2024, None)]
ITEMS = []
for n, (kind, name, year, minutes) in enumerate(TITLES):
    item = {"Id": f"i{n}", "Type": kind, "Name": name, "ProductionYear": year,
            "ImageTags": {"Primary": "p"}, "BackdropImageTags": ["b"], "ProviderIds": {"Tmdb": str(100 + n)}}
    if minutes:
        item["RunTimeTicks"] = minutes * 600_000_000
    else:
        item["ChildCount"] = 2 + n % 3
    ITEMS.append(item)


def jf_get(url, key):
    import urllib.parse as up
    parts = up.urlsplit(url)
    path, query = parts.path, dict(up.parse_qsl(parts.query))
    if path == "/Users":
        return json.dumps([{"Id": "u1", "Name": "casa", "Policy": {"IsAdministrator": True}}]).encode()
    if path.endswith("/Items/Resume"):
        half = []
        for n, pct in ((2, 62.0), (6, 35.0)):
            item = dict(ITEMS[n])
            item["UserData"] = {"PlayedPercentage": pct}
            half.append(item)
        return json.dumps({"Items": half}).encode()
    if path.endswith("/Items/Latest"):
        types = query.get("IncludeItemTypes", "")
        if types == "Movie":
            return json.dumps([i for i in ITEMS if i["Type"] == "Movie"]).encode()
        if types == "Episode,Series":
            return json.dumps([i for i in ITEMS if i["Type"] == "Series"]).encode()
        return json.dumps(ITEMS).encode()
    if path.endswith("/Items"):
        return json.dumps({"Items": ITEMS}).encode()
    if "/Images/" in path:
        item_id = path.split("/Items/")[1].split("/")[0]
        seed = int(item_id[1:])
        wide = "/Backdrop" in path
        return save_png(art(seed, 960, 540) if wide else art(seed, 400, 600))
    return b"{}"


LIGHTS = [("light.ceiling", "Ceiling", "Living room", "on", 204), ("light.shelf", "Shelf", "Living room", "on", 120),
          ("light.lamp", "Lamp", "Bedroom", "off", None), ("light.desk", "Desk", "Office", "on", 255)]


def ha_get(url, token):
    states = [{"entity_id": e, "state": s,
               "attributes": {"friendly_name": n, **({"brightness": b} if b else {}),
                              "supported_color_modes": ["color_temp"] if b else ["onoff"]}}
              for e, n, _a, s, b in LIGHTS]
    states.append({"entity_id": "media_player.tv", "state": "on",
                   "attributes": {"friendly_name": "TV", "source": "PC", "source_list": ["PC", "HDMI 2"]}})
    return states


def ha_post(url, token, payload):
    if url.endswith("/template"):
        return json.dumps({e: a for e, _n, a, _s, _b in LIGHTS})
    return "[]"


def tmdb_get(url, key):
    """Every list TMDB is asked for: the made-up titles, all recent, in this order."""
    recent = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    results = [{"id": 100 + n, "media_type": "movie" if kind == "Movie" else "tv", "popularity": 100 - n,
                "genre_ids": [], ("release_date" if kind == "Movie" else "first_air_date"): recent,
                ("title" if kind == "Movie" else "name"): name}
               for n, (kind, name, _y, _m) in enumerate(TITLES)]
    if "/movie" in url:
        results = [r for r in results if r["media_type"] == "movie"]
    elif "/tv" in url:
        results = [r for r in results if r["media_type"] == "tv"]
    return {"results": results, "total_pages": 1}


def weather_fetch(url):
    today = datetime.date.today()
    hours = [f"{today}T{h:02d}:00" for h in range(24)] + [f"{today + datetime.timedelta(days=1)}T{h:02d}:00" for h in range(24)]
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    codes = [0, 1, 2, 2, 3, 61, 80, 2, 1, 0, 95, 3]
    return {"current": {"time": now, "temperature_2m": 24.6, "weather_code": 2, "is_day": 1},
            "hourly": {"time": hours, "temperature_2m": [18 + 8 * math.sin((h % 24 - 9) / 24 * 2 * math.pi) for h in range(48)],
                       "weather_code": [codes[h % 12] for h in range(48)],
                       "is_day": [1 if 6 <= h % 24 < 19 else 0 for h in range(48)],
                       "precipitation_probability": [[0, 5, 10, 20, 40, 70][h % 6] for h in range(48)]},
            "daily": {"time": [str(today + datetime.timedelta(days=d)) for d in range(6)],
                      "weather_code": [2, 61, 95, 1, 0, 3], "temperature_2m_max": [28, 26, 24, 27, 30, 29],
                      "temperature_2m_min": [18, 17, 16, 17, 19, 20],
                      "sunrise": [f"{today}T05:12"] * 6, "sunset": [f"{today}T18:41"] * 6,
                      "precipitation_probability_max": [10, 60, 85, 5, 0, 20]}}


cfg = json.load(open(os.path.join(ROOT, "config", "apps.json")))
cfg["language"] = "en"
names = {"rocks.shy.VacuumTube": "video", "org.jellyfin.JellyfinDesktop": "media",
         "com.moonlight_stream.Moonlight": "stream", "com.valvesoftware.Steam": "games"}
order = ["org.jellyfin.JellyfinDesktop", "rocks.shy.VacuumTube", "com.valvesoftware.Steam", "com.moonlight_stream.Moonlight"]
cfg["apps"] = sorted(cfg["apps"], key=lambda a: order.index(a["id"]))
for a in cfg["apps"]:
    a["icon"] = f"{icons}/{names[a['id']]}.png"
    a["launch"] = ["true"]
cfg["jellyfin"] = {"url": "http://jellyfin:8096", "api_key": "k"}
cfg["tmdb"] = {"api_key": "a" * 32}
cfg["weather"] = {"name": "Lisbon", "latitude": -22.9, "longitude": -47.06}
cfg["home_assistant"] = {"url": "http://ha:8123", "token": "T", "tv_entity": "media_player.tv",
                         "devices": [e for e, *_ in LIGHTS], "group_by_area": True,
                         "quick_source": {"source": "HDMI 2", "label": "Console"}, "htpc_source": "PC"}
json.dump(cfg, open(f"{home}/.config/htpc-launcher/apps.json", "w"))

import fakes  # noqa: E402

fakes.state["windows"] = []
fakes.state["focus"] = "htpc-launcher"
fakes.start()
time.sleep(0.4)

import launcher  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402
from htpc.backends.base import Battery, PadStatus  # noqa: E402

state = {}
orig_init = launcher.Launcher.__init__


def init(self, app):
    Gtk.Settings.get_default().set_property("gtk-enable-animations", False)
    size = os.environ.get("PREVIEW_SIZE")   # e.g. 3840x2160, to see a 4K TV
    if size:
        launcher.Gtk.Window.set_default_size = (
            lambda win, w, h, _f=Gtk.Window.set_default_size: _f(win, *map(int, size.split("x"))))
    self.weather_fetch = weather_fetch
    self.jellyfin_get, self.tmdb_get, self.ha_get, self.ha_api_post = jf_get, tmdb_get, ha_get, ha_post
    orig_init(self, app)
    self.weather_fetch = weather_fetch
    self.jellyfin_get, self.tmdb_get, self.ha_get, self.ha_api_post = jf_get, tmdb_get, ha_get, ha_post
    state["l"] = self


launcher.Launcher.__init__ = init


def shot(name):
    win = state["l"].win
    p = Gtk.WidgetPaintable.new(win)
    snap = Gtk.Snapshot()
    p.snapshot(snap, win.get_width(), win.get_height())
    node = snap.to_node()
    if node is None:   # GTK had no frame to give yet; happens now and then under Xvfb
        print("skipped", name, flush=True)
        return
    tex = win.get_native().get_renderer().render_texture(node, None)
    tex.save_to_png(os.path.join(OUT, f"{name}.png"))
    print("saved", name, flush=True)


SHOTS = os.path.join(OUT, "screenshots")
os.makedirs(SHOTS, exist_ok=True)


def shot_detail(name):
    """A screenshot for the README's Screenshots section (docs/screenshots/)."""
    global OUT
    out, OUT = OUT, SHOTS
    try:
        shot(name)
    finally:
        OUT = out


def s1():
    l = state["l"]
    l.gamepads.pads = lambda: [PadStatus("Xbox Wireless Controller", "xbox", Battery("x", 85)),
                               PadStatus("Wireless Controller", "playstation", Battery("p", 45))]
    l._update_gamepads()
    l.update_weather()
    l.update_house()
    l.refresh_source_button()
    l.tiles[0].grab_focus()
    l.update_media(force=True)
    l.refresh_resume()


def s2():
    l = state["l"]
    l.tiles[0].grab_focus()
    l.select_tab("explore")
    shot("preview")
    shot_detail("home")
    l.tab_buttons["resume"].grab_focus()


def s2b():
    shot_detail("continue-watching")
    l = state["l"]
    l.select_tab("explore")
    l.tiles[0].grab_focus()
    l.move(0, 1)


def s3():
    shot_detail("lights-by-room")
    state["l"].move(0, 1)


def s3b():
    shot("preview-house")
    shot_detail("forecast")
    l = state["l"]
    tile = next(t for t in l.device_tiles if t.device.get("dimmable"))
    l.open_light(tile)


def s4():
    shot_detail("light-settings")
    l = state["l"]
    while l.overlays:
        l.pop_overlay()
    l.tiles[0].grab_focus()
    l._scroll_to(0.0)
    l.power_menu()


def s5():
    shot_detail("power-menu")
    l = state["l"]
    while l.overlays:
        l.pop_overlay()
    l.open_settings()


def s6():
    shot_detail("settings")
    from types import SimpleNamespace
    from htpc.backends.base import AudioOutput
    l = state["l"]
    l.audio = SimpleNamespace(outputs=lambda: [AudioOutput("hdmi", "TV (HDMI)", current=True),
                                               AudioOutput("bt", "Soundbar", bluetooth=True)])
    l.open_audio()


def s7():
    shot_detail("audio")
    l = state["l"]
    while l.overlays:
        l.pop_overlay()
    l.gamepads.pads = lambda: [PadStatus("Wireless Controller", "playstation", Battery("p", 80))]
    l._update_gamepads()
    l.toggle_edit_mode()
    l.tiles[1].grab_focus()


def s8():
    shot_detail("edit-mode-playstation")
    l = state["l"]
    l.toggle_edit_mode()
    l.show_screensaver()


def s9():
    shot_detail("screensaver")
    state["l"].win.get_application().quit()


steps = [(2500, s1), (2500, s2), (2500, s2b), (700, s3), (700, s3b), (700, s4), (600, s5), (600, s6),
         (900, s7), (700, s8), (3000, s9)]
total = 0
for delay, f in steps:
    total += delay
    GLib.timeout_add(total, lambda f=f: (f(), False)[1])
sys.argv = ["launcher.py"]
launcher.main()
