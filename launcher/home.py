# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The home screen's rows around the apps (mixed into the Launcher class).

  * "Recently added" (above the apps): the newest films and series on the
    Jellyfin server, set up in Settings → Jellyfin. Selecting one opens the
    Jellyfin app.
  * "Home" (below the apps, scrolled into view by going down): lights,
    switches and scenes from Home Assistant, set up in Settings → Home
    Assistant. Ⓐ turns one on or off; Ⓨ on a dimmable light sets its brightness.

Both are fetched off the screen's thread, only while the launcher is in front,
and simply stay hidden when not set up or unreachable.
"""

import sys
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from htpc import home_assistant, jellyfin
from background import in_background

RECENT_EVERY = 10 * 60     # seconds between "recently added" updates
HOUSE_EVERY = 5            # seconds between light/switch state updates
HOUSE_COLUMNS = 6
HOUSE_SETTLE_MS = 700      # after a press: ask Home Assistant again this much later
WIDE = (512, 288)          # the first "recently added" card (16:9)
POSTER = (192, 288)        # the others (2:3)
SCROLL_MS = 180
BRIGHTNESS_STEP = 10


def log(*args):
    print("[launcher]", *args, file=sys.stderr, flush=True)


def _clear(box):
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


class MediaCard(Gtk.Button):
    """A film or series: its picture (when it arrives), the title over a dark band."""

    def __init__(self, item, wide, label, detail, on_activate):
        super().__init__()
        self.item = item
        self.add_css_class("media-card")
        if wide:
            self.add_css_class("wide")
        self.set_focus_on_click(False)
        w, h = WIDE if wide else POSTER
        stack = Gtk.Overlay()
        stack.set_size_request(w, h)
        self.picture = Gtk.Picture(can_shrink=True)
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_size_request(w, h)
        self.picture.add_css_class("media-picture")
        stack.set_child(self.picture)
        band = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.END)
        band.add_css_class("media-band")
        if wide and label:
            kind = Gtk.Label(label=label, xalign=0)
            kind.add_css_class("media-kind")
            band.append(kind)
        title = Gtk.Label(label=item["title"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                          max_width_chars=28 if wide else 12)
        title.add_css_class("media-title")
        band.append(title)
        if detail:
            d = Gtk.Label(label=detail, xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=40 if wide else 18)
            d.add_css_class("media-detail")
            band.append(d)
        stack.add_overlay(band)
        self.set_child(stack)
        self.connect("clicked", lambda _b: on_activate(self))

    def set_texture(self, texture):
        self.picture.set_paintable(texture)


class DeviceTile(Gtk.Button):
    """A light or switch: icon, name, room, and whether it is on."""

    def __init__(self, device, t, icon, on_activate):
        super().__init__()
        self.add_css_class("device")
        self.set_focus_on_click(False)
        self.t, self.icon_for = t, icon
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        top = Gtk.Box(spacing=10)
        self.badge = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.CENTER)
        self.badge.add_css_class("device-badge")
        self.icon = Gtk.Image(pixel_size=26, hexpand=True, halign=Gtk.Align.CENTER)
        self.badge.append(self.icon)
        self.area = Gtk.Label(xalign=1, hexpand=True, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
        self.area.add_css_class("device-area")
        top.append(self.badge)
        top.append(self.area)
        self.name = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=16)
        self.name.add_css_class("device-name")
        self.state = Gtk.Label(xalign=0)
        self.state.add_css_class("device-state")
        box.append(top)
        box.append(self.name)
        box.append(self.state)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_activate(self))
        self.update(device)

    def update(self, device):
        self.device = device
        on, light = device["on"], device["domain"] == "light"
        self.icon.set_from_gicon(self.icon_for(("light" if light else "plug") + ("-on" if on else "") + ".svg"))
        self.icon.set_pixel_size(26)
        self.area.set_label(device.get("area") or "")
        self.name.set_label(device["name"])
        if not device["available"]:
            text = self.t("dev_unavailable")
        elif on and device.get("brightness") is not None:
            text = self.t("dev_brightness", pct=device["brightness"])
        else:
            text = self.t(("dev_on" if on else "dev_off") + ("_light" if light else ""))
        self.state.set_label(text)
        for css, cond in (("on", on), ("unavailable", not device["available"])):
            if cond:
                self.add_css_class(css)
            else:
                self.remove_css_class(css)


class HomeMixin:
    # --- building ---------------------------------------------------------------------

    def _home_body(self):
        """The scrolling middle of the screen: recently added, the apps, the house."""
        self.recent_items, self.recent_cards, self.recent_fetched = [], [], 0.0
        self.textures = getattr(self, "textures", {})
        self.house_data = None
        self.device_tiles, self.scene_buttons = [], []
        self.scroll_target = None

        self.scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44)
        self.content.add_css_class("home-content")
        self.content.set_margin_bottom(48)   # the last row of the house clears the footer

        self.recent_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.recent_section.append(self._section_title(self.t("recent_title"), self.t("recent_source")))
        recent_scroll = Gtk.ScrolledWindow()
        recent_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.recent_box = Gtk.Box(spacing=28)
        self.recent_box.add_css_class("recent-row")
        recent_scroll.set_child(self.recent_box)
        self.recent_section.append(recent_scroll)
        self.recent_section.set_visible(False)

        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True)
        self.grid.add_css_class("apps")

        self.house_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        self.house_title = self._section_title(self.t("house_title"), "")
        self.house_section.append(self.house_title)
        self.scene_box = Gtk.Box(spacing=18)
        self.house_section.append(self.scene_box)
        self.device_grid = Gtk.Grid(column_spacing=20, row_spacing=20, column_homogeneous=True)
        self.house_section.append(self.device_grid)
        self.house_section.set_visible(False)

        for w in (self.recent_section, self.grid, self.house_section):
            self.content.append(w)
        self.scroller.set_child(self.content)
        viewport = self.scroller.get_child()
        if isinstance(viewport, Gtk.Viewport):
            viewport.set_scroll_to_focus(False)   # _focus_moved scrolls, by rows
        return self.scroller

    def _section_title(self, title, note):
        line = Gtk.Box(spacing=14)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class("section-title")
        line.append(t)
        line.note = Gtk.Label(label=note, xalign=0)
        line.note.add_css_class("section-note")
        line.append(line.note)
        return line

    def _relayout(self):
        """The apps sit in the middle of the screen when they are alone, at the top
        of their space when other rows are shown."""
        alone = not (self.recent_section.get_visible() or self.house_section.get_visible())
        self.grid.set_vexpand(alone)
        self.grid.set_valign(Gtk.Align.CENTER if alone else Gtk.Align.START)

    @property
    def recent_row(self):
        return list(self.recent_cards) if self.recent_section.get_visible() else []

    @property
    def house_rows(self):
        if not self.house_section.get_visible():
            return []
        rows = [list(self.scene_buttons)] if self.scene_buttons else []
        tiles = self.device_tiles
        rows += [tiles[i:i + HOUSE_COLUMNS] for i in range(0, len(tiles), HOUSE_COLUMNS)]
        return rows

    # --- recently added (Jellyfin) ---------------------------------------------------------

    def update_recent(self, force=False):
        if not jellyfin.ready(self.cfg):
            self._show_recent([])
            return False
        if not force and time.monotonic() - self.recent_fetched < RECENT_EVERY:
            return False
        self.recent_fetched = time.monotonic()
        cfg, get = dict(self.cfg), getattr(self, "jellyfin_get", None)
        in_background(lambda: jellyfin.latest(cfg, get), self._recent_arrived)
        return False

    def _recent_arrived(self, result):
        if isinstance(result, Exception):
            log("recently added not updated:", result)
            self.recent_fetched = time.monotonic() - RECENT_EVERY + 60   # try again in a minute
            return
        self._show_recent(result)

    def _media_detail(self, item):
        if item["kind"] == "movie":
            parts = [str(item["year"])] if item.get("year") else []
            if item.get("minutes"):
                h, m = divmod(item["minutes"], 60)
                parts.append(f"{h}h{m:02d}" if h else f"{m} min")
            return " · ".join(parts)
        if item["kind"] == "series":
            n = item.get("new_count") or 0
            return self.t("media_new_episodes", n=n) if n > 1 else (self.t("media_new_episode") if n else "")
        if item.get("season") is not None and item.get("episode") is not None:
            text = self.t("media_episode", season=item["season"], episode=item["episode"])
            return f"{text} · {item['episode_name']}" if item.get("episode_name") else text
        return item.get("episode_name") or ""

    def _show_recent(self, items):
        if [i["id"] for i in items] == [i["id"] for i in self.recent_items] and self.recent_cards:
            return
        focused = self.win.get_focus()
        had_focus = focused in self.recent_cards
        self.recent_items = items
        _clear(self.recent_box)
        self.recent_cards = []
        for n, item in enumerate(items):
            wide = n == 0
            label = self.t("media_kind_" + ("movie" if item["kind"] == "movie" else "series"))
            card = MediaCard(item, wide, label, self._media_detail(item), self.open_media)
            url = (item.get("backdrop") or item.get("poster")) if wide else (item.get("poster") or item.get("backdrop"))
            if url:
                self._load_picture(card, url)
            self.recent_box.append(card)
            self.recent_cards.append(card)
        self.recent_section.set_visible(bool(items))
        self._relayout()
        if had_focus:
            (self.recent_cards[0] if self.recent_cards else self.tiles[0] if self.tiles else self.btn_settings).grab_focus()

    def _load_picture(self, card, url):
        texture = self.textures.get(url)
        if texture is not None:
            card.set_texture(texture)
            return
        cfg, get = dict(self.cfg), getattr(self, "jellyfin_get", None)

        def arrived(data):
            if isinstance(data, Exception):
                log("no picture for", card.item["title"], ":", data)
                return
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except GLib.Error as e:
                log("bad picture for", card.item["title"], ":", e)
                return
            self.textures[url] = texture
            card.set_texture(texture)

        in_background(lambda: jellyfin.image(cfg, url, get), arrived)

    def open_media(self, card):
        """Jellyfin opens on its home screen, where the new items are on top."""
        tile = next((t for t in self.tiles if "jellyfin" in t.app.get("id", "").lower()), None)
        if tile is None:
            self._message(self.t("jf_no_app"))
            return
        self.open_app(tile)

    # --- the house (Home Assistant) --------------------------------------------------------

    def update_house(self):
        if not home_assistant.home_ready(self.cfg):
            self._show_house(None)
            return False
        cfg, get, post = dict(self.cfg), getattr(self, "ha_get", None), getattr(self, "ha_api_post", None)
        in_background(lambda: home_assistant.house(cfg, get, post), self._house_arrived)
        return False

    def _house_arrived(self, result):
        if isinstance(result, Exception):
            log("Home Assistant states not updated:", result)
            return   # keep showing the last ones
        if not home_assistant.home_ready(self.cfg):
            result = None   # switched off meanwhile
        self._show_house(result)

    def _show_house(self, data):
        devices = (data or {}).get("devices") or []
        scenes = (data or {}).get("scenes") or []
        self.house_data = data
        same = ([d["entity"] for d in devices] == [t.device["entity"] for t in self.device_tiles]
                and [s["entity"] for s in scenes] == [b.scene["entity"] for b in self.scene_buttons])
        if same:
            for tile, device in zip(self.device_tiles, devices):
                tile.update(device)
        else:
            focused = self.win.get_focus()
            keep = getattr(focused, "device", None) or getattr(focused, "scene", None)
            _clear(self.scene_box)
            child = self.device_grid.get_first_child()
            while child is not None:
                following = child.get_next_sibling()
                self.device_grid.remove(child)
                child = following
            self.scene_buttons = []
            for scene in scenes:
                b = Gtk.Button(label=scene["name"])
                b.add_css_class("scene")
                b.set_focus_on_click(False)
                b.scene = scene
                b.connect("clicked", lambda _b, e=scene["entity"]: self.run_scene(e))
                self.scene_box.append(b)
                self.scene_buttons.append(b)
            self.device_tiles = []
            for n, device in enumerate(devices):
                tile = DeviceTile(device, self.t, self.svg_icon, self.on_device)
                self.device_grid.attach(tile, n % HOUSE_COLUMNS, n // HOUSE_COLUMNS, 1, 1)
                self.device_tiles.append(tile)
            for n in range(len(devices), HOUSE_COLUMNS):   # a short first row keeps the column width
                self.device_grid.attach(Gtk.Box(), n, 0, 1, 1)
            self.scene_box.set_visible(bool(scenes))
            if keep is not None:
                target = next((w for w in self.device_tiles + self.scene_buttons
                               if (getattr(w, "device", None) or getattr(w, "scene", None))["entity"] == keep["entity"]),
                              None)
                (target or (self.tiles[0] if self.tiles else self.btn_settings)).grab_focus()
        on = sum(1 for d in devices if d["on"])
        self.house_title.note.set_label(self.t("house_note", n=on))
        self.house_section.set_visible(bool(devices or scenes))
        self._relayout()

    def on_device(self, tile):
        device = tile.device
        if not device["available"]:
            return
        # Shown at once; Home Assistant's own answer follows a moment later.
        tile.update({**device, "on": not device["on"],
                     "brightness": None if device["on"] else device.get("brightness")})
        self._house_call(lambda cfg, post: home_assistant.toggle(cfg, device["entity"], post))

    def run_scene(self, entity):
        self._house_call(lambda cfg, post: home_assistant.toggle(cfg, entity, post))

    def _house_call(self, job):
        cfg, post = dict(self.cfg), getattr(self, "ha_api_post", None)

        def done(result):
            if isinstance(result, Exception):
                log("Home Assistant call failed:", result)
            GLib.timeout_add(HOUSE_SETTLE_MS, lambda: self.update_house() and False)

        in_background(lambda: job(cfg, post), done)

    def open_brightness(self, tile):
        """Ⓨ on a dimmable light: − / + in steps of 10 %, and on / off."""
        device = tile.device
        box = self.dialog_box(device["name"])
        value = Gtk.Label()
        value.add_css_class("brightness-value")
        box.append(value)
        level = {"pct": device.get("brightness") or (0 if not device["on"] else 100)}

        def show():
            value.set_label(f"{level['pct']}%" if level["pct"] else self.t("dev_off_light"))

        def change(pct):
            level["pct"] = max(0, min(100, pct))
            show()
            tile.update({**tile.device, "on": level["pct"] > 0, "brightness": level["pct"] or None})
            p = level["pct"]
            self._house_call(lambda cfg, post: home_assistant.set_brightness(cfg, device["entity"], p, post))

        minus = self.dialog_button("−", lambda: change((level["pct"] or 0) - BRIGHTNESS_STEP))
        plus = self.dialog_button("+", lambda: change((level["pct"] or 0) + BRIGHTNESS_STEP))
        off = self.dialog_button(self.t("turn_off"), lambda: change(0))
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        for b in (minus, plus):
            b.add_css_class("brightness-step")
        buttons = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        for b in (minus, plus, off, close):
            buttons.append(b)
        box.append(buttons)
        show()
        self.brightness_value = value
        self.push_overlay(box, [[minus, plus, off, close]], focus=plus)

    # --- timers and scrolling --------------------------------------------------------------

    def _home_tick(self):
        if self.win.is_active():
            self.update_recent()
            if not self.overlays:
                self.update_house()
        return True

    def _focus_moved(self, *_):
        """Scroll so the focused row shows: the top (recently added and the apps)
        for anything above the house; in the house, the apps' row just above it."""
        focused = self.win.get_focus()
        if focused is None or self.overlays or not focused.is_ancestor(self.content):
            return
        in_house = focused.is_ancestor(self.house_section)
        if in_house:
            self.grid.add_css_class("dimmed")
        else:
            self.grid.remove_css_class("dimmed")
        adj = self.scroller.get_vadjustment()
        page = adj.get_page_size()
        if not in_house:
            target = 0.0
            ok, r = focused.compute_bounds(self.content)
            if ok and r.get_y() + r.get_height() > page:   # a tall screen of apps
                target = r.get_y() + r.get_height() - page + 40
        else:
            ok_g, g = self.grid.compute_bounds(self.content)
            ok, r = focused.compute_bounds(self.content)
            if not (ok and ok_g):
                return
            target = g.get_y() + g.get_height() * 0.55   # the apps' lower half stays in view
            bottom = r.get_y() + r.get_height() + 40
            if bottom - target > page:
                target = bottom - page
        target = max(0.0, min(target, adj.get_upper() - page))
        self._scroll_to(target)

    def _scroll_to(self, target):
        adj = self.scroller.get_vadjustment()
        self.scroll_target = target
        if not Gtk.Settings.get_default().get_property("gtk-enable-animations"):
            adj.set_value(target)
            return
        start, began = adj.get_value(), time.monotonic()

        def frame():
            if self.scroll_target != target:
                return False   # a newer scroll took over
            t = min(1.0, (time.monotonic() - began) * 1000 / SCROLL_MS)
            ease = 1 - (1 - t) ** 3
            adj.set_value(start + (target - start) * ease)
            return t < 1.0

        GLib.timeout_add(16, frame)
