# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The home screen's rows around the apps (mixed into the Launcher class).

  * Tabs above the apps (moving onto one shows its row):
      - Explore: what is popular this week on TMDB that is in your Jellyfin
        library (without a TMDB key: what was added lately);
      - Series and Films: what was added lately to Jellyfin;
      - Games: the Steam games played most recently.
    A film or series opens the Jellyfin app; a game starts through Steam (or,
    when it is only streamed from another computer, opens its Steam page).
  * "Home" (below the apps, scrolled into view by going down): lights,
    switches and scenes from Home Assistant, set up in Settings → Home
    Assistant. Ⓐ turns one on or off; holding Ⓐ (or Ⓨ) on a light opens its
    brightness, colour temperature and colour. They can be shown by room.

Both are fetched off the screen's thread, only while the launcher is in front,
and simply stay hidden when not set up or unreachable.
"""

import sys
import time

from gi.repository import Gdk, GLib, Gtk, Pango

from htpc import home_assistant, jellyfin, steam, tmdb
from background import in_background

TABS = ("explore", "resume", "series", "movies", "games")
PAGE_SIZE = 5              # cards a page: one wide and four posters; RB / LB turn the page
TAB_EVERY = {"resume": 2 * 60, "explore": 60 * 60, "series": 10 * 60, "movies": 10 * 60, "games": 60}   # seconds
HOUSE_EVERY = 5            # seconds between light/switch state updates
HOUSE_COLUMNS = 6
DEVICE_WIDTH = 240         # px of a light's card when shown by room
HOUSE_SETTLE_MS = 700      # after a press: ask Home Assistant again this much later
WIDE = (512, 288)          # the first "recently added" card (16:9)
POSTER = (192, 288)        # the others (2:3)
SCROLL_MS = 180
BRIGHTNESS_STEP = 10
TEMPERATURES = (2200, 2700, 3000, 4000, 5000, 6500)   # kelvin, offered within the light's range
COLORS = (("red", (0, 100)), ("orange", (28, 100)), ("yellow", (52, 100)), ("green", (120, 90)),
          ("cyan", (185, 90)), ("blue", (225, 100)), ("purple", (275, 90)), ("pink", (320, 70)))


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
        if item.get("progress") is not None:
            self.progress = Gtk.ProgressBar(fraction=item["progress"] / 100)
            self.progress.add_css_class("media-progress")
            band.append(self.progress)
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


class TabButton(Gtk.Button):
    """One of Explore / Series / Films / Games. Moving onto it shows its row."""

    def __init__(self, name, label):
        super().__init__(label=label)
        self.tab = name
        self.add_css_class("tab")
        self.set_focus_on_click(False)


class HomeMixin:
    # --- building ---------------------------------------------------------------------

    def _home_body(self):
        """The scrolling middle of the screen: the media tabs, the apps, the house."""
        self.media = getattr(self, "media", {tab: [] for tab in TABS})
        self.media_fetched = getattr(self, "media_fetched", {tab: 0.0 for tab in TABS})
        self.media_tab = getattr(self, "media_tab", TABS[0])
        self.media_context = getattr(self, "media_context", None)   # "jellyfin", "steam" or None
        self.context_tab = getattr(self, "context_tab", {})          # the last tab used per app
        self.media_page = getattr(self, "media_page", {tab: 0 for tab in TABS})
        self.media_shown = None
        self.recent_cards = []
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
        tabs_line = Gtk.Box(spacing=12)
        tabs_line.set_size_request(-1, 58)   # the same height with or without tabs: nothing jumps
        self.tab_buttons = {tab: TabButton(tab, self.t("tab_" + tab)) for tab in TABS}
        for b in self.tab_buttons.values():
            tabs_line.append(b)
        self.media_note = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.media_note.add_css_class("section-note")
        self.media_note.set_margin_start(18)
        tabs_line.append(self.media_note)
        self.recent_section.append(tabs_line)
        recent_scroll = Gtk.ScrolledWindow()
        recent_scroll.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.recent_box = Gtk.Box(spacing=28)
        self.recent_box.add_css_class("recent-row")
        self.recent_box.set_size_request(-1, WIDE[1] + 32)
        recent_scroll.set_child(self.recent_box)
        self.recent_section.append(recent_scroll)
        # LB / RB turn the page: said under the cards, in a line that is always there
        # (empty with one page), so nothing jumps.
        self.page_hint = Gtk.Label(xalign=0)
        self.page_hint.add_css_class("section-note")
        self.page_hint.add_css_class("page-hint")
        self.recent_section.append(self.page_hint)
        self.media_empty = Gtk.Label(xalign=0)
        self.media_empty.add_css_class("media-empty")
        self.media_empty.set_visible(False)
        tabs_line.append(self.media_empty)
        self.recent_section.set_visible(False)

        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, vexpand=True)
        self.grid.add_css_class("apps")

        self.house_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        self.house_title = self._section_title(self.t("house_title"), "")
        self.house_section.append(self.house_title)
        self.scene_box = Gtk.Box(spacing=18)
        self.house_section.append(self.scene_box)
        self.device_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.house_section.append(self.device_box)
        self.device_rows, self.house_grouped = [], None
        self.house_section.set_visible(False)

        self.forecast_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        self.forecast_title = self._section_title(self.t("forecast_title"), "")
        self.forecast_section.append(self.forecast_title)
        self.hours_box = Gtk.Box(spacing=12)
        self.hours_box.add_css_class("forecast-hours")
        self.forecast_section.append(self.hours_box)
        self.days_box = Gtk.Box(spacing=20)
        self.forecast_section.append(self.days_box)
        self.day_cards = []
        self.forecast_section.set_visible(False)

        for w in (self.recent_section, self.grid, self.house_section, self.forecast_section):
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
        alone = not (self.recent_section.get_visible() or self.house_section.get_visible()
                     or self.forecast_section.get_visible())
        self.grid.set_vexpand(alone)
        self.grid.set_valign(Gtk.Align.CENTER if alone else Gtk.Align.START)

    @property
    def tab_row(self):
        if not self.recent_section.get_visible():
            return []
        return [b for b in self.tab_buttons.values() if b.get_visible()]

    @property
    def recent_row(self):
        return list(self.recent_cards) if self.recent_section.get_visible() else []

    @property
    def house_rows(self):
        """The house, then the forecast's days (both below the apps)."""
        rows = []
        if self.house_section.get_visible():
            rows = ([list(self.scene_buttons)] if self.scene_buttons else []) + [list(r) for r in self.device_rows]
        if self.forecast_section.get_visible() and self.day_cards:
            rows.append(list(self.day_cards))
        return rows

    # --- the forecast (below the house) --------------------------------------------------

    def show_forecast(self, conditions):
        """The next hours and days, under the house. Hidden without a forecast."""
        forecast = getattr(conditions, "forecast", None)
        if not forecast or not forecast.days:
            self.forecast_section.set_visible(False)
            self._relayout()
            return
        focused = self.win.get_focus()
        had_focus = focused in self.day_cards
        index = self.day_cards.index(focused) if had_focus else 0
        _clear(self.hours_box)
        _clear(self.days_box)
        note = self.t("forecast_sun", rise=forecast.sunrise, set=forecast.sunset) if forecast.sunrise else ""
        self.forecast_title.note.set_label(note)
        for hour in forecast.hours:
            chip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            chip.add_css_class("forecast-hour")
            when = Gtk.Label(label=self.t("forecast_now") if hour is forecast.hours[0] else f"{hour.hour:02d}h")
            when.add_css_class("forecast-when")
            icon = Gtk.Image.new_from_gicon(self.svg_icon(hour.icon))
            icon.set_pixel_size(34)
            temp = Gtk.Label(label=f"{hour.temperature}°")
            temp.add_css_class("forecast-temp")
            rain = Gtk.Label(label=f"{hour.rain}%" if hour.rain else "")
            rain.add_css_class("forecast-rain")
            for w in (when, icon, temp, rain):
                chip.append(w)
            self.hours_box.append(chip)
        self.day_cards = []
        weekdays = self.t.strings["weekdays"]
        for n, day in enumerate(forecast.days):
            card = Gtk.Button()
            card.add_css_class("forecast-day")
            card.set_focus_on_click(False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            try:
                weekday = weekdays[time.strptime(day.date, "%Y-%m-%d").tm_wday]
            except ValueError:
                weekday = day.date
            name = Gtk.Label(label=self.t("forecast_today") if n == 0 else weekday.split("-")[0].capitalize(), xalign=0)
            name.add_css_class("forecast-day-name")
            icon = Gtk.Image.new_from_gicon(self.svg_icon(day.icon))
            icon.set_pixel_size(48)
            icon.set_halign(Gtk.Align.START)
            temps = Gtk.Label(label=f"{day.high}° / {day.low}°", xalign=0)
            temps.add_css_class("forecast-temps")
            rain = Gtk.Label(label=self.t("forecast_rain", pct=day.rain) if day.rain else " ", xalign=0)
            rain.add_css_class("forecast-rain")
            for w in (name, icon, temps, rain):
                box.append(w)
            card.set_child(box)
            card.set_size_request(DEVICE_WIDTH, -1)
            card.set_hexpand(False)
            self.days_box.append(card)
            self.day_cards.append(card)
        self.forecast_section.set_visible(True)
        if had_focus:
            self.day_cards[min(index, len(self.day_cards) - 1)].grab_focus()
        self._relayout()

    # --- the media tabs: Explore, Series, Films (Jellyfin) and Games (Steam) ------------------

    def steam_home(self):
        return getattr(self, "steam_home_dir", None)

    def context_tabs(self, context):
        """The tabs of the app in focus: Jellyfin's films and series, or Steam's games."""
        if context == "jellyfin" and jellyfin.ready(self.cfg):
            # "Continue watching" only while something is half watched.
            return ["explore"] + (["resume"] if self.media.get("resume") else []) + ["series", "movies"]
        if context == "steam" and steam.available(self.steam_home()):
            return ["games"]
        return []

    def fetchable_tabs(self):
        """Every row kept up to date, shown or not ("resume" is hidden while empty)."""
        tabs = self.context_tabs("jellyfin") + self.context_tabs("steam")
        return (["resume"] if jellyfin.ready(self.cfg) and "resume" not in tabs else []) + tabs

    def refresh_resume(self):
        """Back from watching something: what is half watched has changed."""
        if jellyfin.ready(self.cfg):
            self._fetch_tab("resume")

    def media_ready(self):
        """Is there anything the row above the apps could show (for some app)?"""
        return bool(self.context_tabs("jellyfin") or self.context_tabs("steam"))

    def available_tabs(self):
        return self.context_tabs(self.media_context)

    @staticmethod
    def context_of(app):
        app_id = (app or {}).get("id", "").lower()
        return "jellyfin" if "jellyfin" in app_id else "steam" if "steam" in app_id else None

    def set_context(self, context):
        """The app in focus changed: show its row (nothing for apps without one)."""
        if context == self.media_context:
            return
        self.media_context = context
        tabs = self.available_tabs()
        if tabs and self.media_tab not in tabs:
            self.media_tab = self.context_tab.get(context) if self.context_tab.get(context) in tabs else tabs[0]
        self.update_media()

    def update_media(self, force=False, tab=None):
        """Fetch rows when they are due (at start: every row there is), then show
        the one of the app in focus."""
        self.recent_section.set_visible(self.media_ready())
        everything = self.fetchable_tabs()
        tabs = self.available_tabs()
        for b in self.tab_buttons.values():
            b.set_visible(b.tab in tabs)
        if tabs and self.media_tab not in tabs:
            self.media_tab = tabs[0]
        for name in ([tab] if tab else everything if force else tabs[:1] and [self.media_tab]):
            if name in everything and (force or time.monotonic() - self.media_fetched[name] >= TAB_EVERY[name]):
                self._fetch_tab(name)
        self._show_media()
        return False

    update_recent = update_media   # its first name, when it was one row

    def _fetch_tab(self, name):
        self.media_fetched[name] = time.monotonic()
        cfg = dict(self.cfg)
        jf_get, tmdb_get = getattr(self, "jellyfin_get", None), getattr(self, "tmdb_get", None)
        if name == "resume":
            job = lambda: jellyfin.resume(cfg, jf_get)   # noqa: E731
        elif name == "explore" and tmdb.ready(cfg):
            job = lambda: jellyfin.explore(cfg, tmdb.ranking(cfg, tmdb_get), jf_get)   # noqa: E731
        elif name == "explore":
            job = lambda: jellyfin.latest(cfg, jf_get)   # noqa: E731 - without TMDB: what's new
        elif name == "series":
            job = lambda: jellyfin.latest(cfg, jf_get, types="Episode,Series")   # noqa: E731
        elif name == "movies":
            job = lambda: jellyfin.latest(cfg, jf_get, types="Movie")   # noqa: E731
        else:
            home, names = self.steam_home(), getattr(self, "steam_names", None)
            job = lambda: steam.recent_games(home, names=names)   # noqa: E731
        in_background(job, lambda result: self._tab_arrived(name, result))

    def _tab_arrived(self, name, result):
        if isinstance(result, Exception):
            log(f"{name} not updated:", result)
            self.media_fetched[name] = time.monotonic() - TAB_EVERY[name] + 60   # try again in a minute
            return
        self.media[name] = result
        if name == self.media_tab or name == "resume":   # the Continue tab comes and goes
            self._show_media()

    def select_tab(self, name):
        if name == self.media_tab:
            return
        self.media_tab = name
        if self.media_context:
            self.context_tab[self.media_context] = name
        for b in self.tab_buttons.values():
            (b.add_css_class if b.tab == name else b.remove_css_class)("selected")
        self.update_media(tab=name)   # shows what is cached, and fetches if it is old

    def _media_note(self):
        if self.media_tab == "explore":
            note = self.t("explore_note" if tmdb.ready(self.cfg) else "explore_note_no_tmdb")
        else:
            note = self.t(f"{self.media_tab}_note")
        if len(self.available_tabs()) > 1:
            note += "    " + self.t("media_tabs_hint")
        return note

    def _page_hint(self):
        pages = self._pages()
        return self.t("media_pages", page=self.media_page[self.media_tab] + 1, pages=pages) if pages > 1 else ""

    def switch_tab(self, step):
        """LT / RT: the previous or next tab of the row in view, keeping the focus
        where it was (on a card: the first card of the new tab)."""
        tabs = self.available_tabs()
        if len(tabs) < 2 or self.overlays or self.media_tab not in tabs:
            return
        name = tabs[(tabs.index(self.media_tab) + step) % len(tabs)]
        focused = self.win.get_focus()
        on_tab, on_card = focused in self.tab_buttons.values(), focused in self.recent_cards
        self.select_tab(name)
        if on_tab:
            self.tab_buttons[name].grab_focus()
        elif on_card and self.recent_cards:
            self.recent_cards[0].grab_focus()

    def _pages(self):
        items = self.media.get(self.media_tab, [])
        return max(1, -(-len(items) // PAGE_SIZE))

    def page_media(self, step):
        """RB / LB: the next or previous few cards of the row in view."""
        if not self.available_tabs() or self.overlays:
            return
        page = max(0, min(self._pages() - 1, self.media_page[self.media_tab] + step))
        if page == self.media_page[self.media_tab]:
            return
        focused = self.win.get_focus()
        index = self.recent_cards.index(focused) if focused in self.recent_cards else None
        self.media_page[self.media_tab] = page
        self._show_media()
        if index is not None and self.recent_cards:
            self.recent_cards[min(index, len(self.recent_cards) - 1)].grab_focus()

    def _media_detail(self, item):
        if item["kind"] == "game":
            days = max(0, int((time.time() - item["last_played"]) // 86400))
            when = self.t("played_today") if days == 0 else self.t("played_yesterday") if days == 1 \
                else self.t("played_days", n=days)
            hours = round(item.get("minutes", 0) / 60)
            return f"{when} · {self.t('played_hours', n=hours)}" if hours else when
        if item.get("progress") is not None:   # Continue watching: where and how long is left
            parts = []
            if item.get("season") is not None and item.get("episode") is not None:
                parts.append(self.t("media_episode", season=item["season"], episode=item["episode"]))
            if item.get("minutes"):
                left = max(1, round(item["minutes"] * (100 - item["progress"]) / 100))
                h, m = divmod(left, 60)
                parts.append(self.t("media_left", time=f"{h}h{m:02d}" if h else f"{m} min"))
            return " · ".join(parts)
        if item["kind"] == "movie":
            parts = [str(item["year"])] if item.get("year") else []
            if item.get("minutes"):
                h, m = divmod(item["minutes"], 60)
                parts.append(f"{h}h{m:02d}" if h else f"{m} min")
            return " · ".join(parts)
        if item["kind"] == "series":
            n = item.get("new_count") or 0
            if n:
                return self.t("media_new_episodes", n=n) if n > 1 else self.t("media_new_episode")
            return str(item["year"]) if item.get("year") else ""
        if item.get("season") is not None and item.get("episode") is not None:
            text = self.t("media_episode", season=item["season"], episode=item["episode"])
            return f"{text} · {item['episode_name']}" if item.get("episode_name") else text
        return item.get("episode_name") or ""

    def _media_label(self, item):
        if item["kind"] == "game":
            return self.t("media_kind_game")
        if self.media_tab == "resume":
            return self.t("media_kind_resume")
        kind = "movie" if item["kind"] == "movie" else "series"
        return self.t(("media_kind_hot_" if self.media_tab == "explore" and tmdb.ready(self.cfg)
                       else "media_kind_") + kind)

    def _show_media(self):
        tabs = self.available_tabs()
        if tabs and self.media_tab not in tabs:   # e.g. Continue watching, now empty
            self.media_tab = tabs[0]
        self.recent_section.set_visible(self.media_ready())
        for b in self.tab_buttons.values():
            b.set_visible(b.tab in tabs)
            (b.add_css_class if b.tab == self.media_tab else b.remove_css_class)("selected")
        all_items = self.media.get(self.media_tab, []) if tabs else []
        pages = max(1, -(-len(all_items) // PAGE_SIZE))
        page = self.media_page[self.media_tab] = min(self.media_page.get(self.media_tab, 0), pages - 1)
        items = all_items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
        self.media_note.set_label(self._media_note() if tabs else "")
        self.page_hint.set_label(self._page_hint() if tabs else "")
        shown = (self.media_tab if tabs else None, page, tuple(i["id"] for i in items))
        if shown != self.media_shown:
            focused = self.win.get_focus()
            had_focus = focused in self.recent_cards
            self.media_shown = shown
            _clear(self.recent_box)
            self.recent_cards = []
            for n, item in enumerate(items):
                wide = n == 0
                card = MediaCard(item, wide, self._media_label(item), self._media_detail(item), self.open_media)
                url = (item.get("backdrop") or item.get("poster")) if wide else (item.get("poster") or item.get("backdrop"))
                if url:
                    self._load_picture(card, url)
                self.recent_box.append(card)
                self.recent_cards.append(card)
            if had_focus:
                (self.recent_cards[0] if self.recent_cards else self.tab_buttons[self.media_tab]).grab_focus()
        fetched = self.media_fetched.get(self.media_tab, 0) > 0
        self.media_empty.set_label(self.t(f"{self.media_tab}_empty") if tabs and fetched and not all_items else "")
        self.media_empty.set_visible(bool(self.media_empty.get_label()))
        self._relayout()

    @property
    def recent_items(self):
        return self.media.get(self.media_tab, [])

    def _show_recent(self, items):
        """Kept for build_ui: show the current tab again after a rebuild."""
        self._show_media()

    def _load_picture(self, card, url):
        texture = self.textures.get(url)
        if texture is not None:
            card.set_texture(texture)
            return
        cfg, get = dict(self.cfg), getattr(self, "jellyfin_get", None)

        steam_get = getattr(self, "steam_image_get", None)

        def fetch():
            if card.item["kind"] == "game":   # Steam's own cache, or its image servers
                return steam.image(url, steam_get)
            return jellyfin.image(cfg, url, get)

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

        in_background(fetch, arrived)

    def open_media(self, card):
        """A film or series opens the Jellyfin app (on its home screen); a game
        starts through Steam."""
        item = card.item
        if item["kind"] == "game":
            tile = next((t for t in self.tiles if "steam" in t.app.get("id", "").lower()), None)
            command = steam.run_command(tile.app if tile else None, item["appid"], item.get("installed", True))
            if tile is not None:
                self.wake_pc_for(tile.app)   # the PC the game streams from
            log("starting", item["title"], command)
            if self._spawn(command) and tile is not None:
                self.opening[tile.app["id"]] = time.monotonic()
                tile.show_status(self.t("status_opening"), running=True, opening=True)
            return
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
        grouped = bool((self.cfg.get("home_assistant") or {}).get("group_by_area"))
        same = ([d["entity"] for d in devices] == [t.device["entity"] for t in self.device_tiles]
                and [d.get("area") for d in devices] == [t.device.get("area") for t in self.device_tiles]
                and [s["entity"] for s in scenes] == [b.scene["entity"] for b in self.scene_buttons]
                and grouped == self.house_grouped)
        if same:
            for tile, device in zip(self.device_tiles, devices):
                tile.update(device)
        else:
            focused = self.win.get_focus()
            keep = getattr(focused, "device", None) or getattr(focused, "scene", None)
            _clear(self.scene_box)
            _clear(self.device_box)
            self.house_grouped = grouped
            self.scene_buttons = []
            for scene in scenes:
                b = Gtk.Button(label=scene["name"])
                b.add_css_class("scene")
                b.set_focus_on_click(False)
                b.scene = scene
                b.connect("clicked", lambda _b, e=scene["entity"]: self.run_scene(e))
                self.scene_box.append(b)
                self.scene_buttons.append(b)
            self.device_tiles, self.device_rows = [], []
            groups = []   # (room name or None, devices)
            for device in devices:
                key = device.get("area") if grouped else None
                if groups and groups[-1][0] == key:
                    groups[-1][1].append(device)
                else:
                    groups.append((key, [device]))
            if grouped:
                self._lay_out_rooms(groups)
            else:
                members = [d for _area, ds in groups for d in ds]
                grid = Gtk.Grid(column_spacing=20, row_spacing=20, column_homogeneous=True)
                tiles = []
                for n, device in enumerate(members):
                    tile = DeviceTile(device, self.t, self.svg_icon, self.on_device)
                    grid.attach(tile, n % HOUSE_COLUMNS, n // HOUSE_COLUMNS, 1, 1)
                    tiles.append(tile)
                for n in range(len(members), HOUSE_COLUMNS):   # a short row keeps the column width
                    grid.attach(Gtk.Box(), n, 0, 1, 1)
                self.device_box.append(grid)
                self.device_tiles += tiles
                self.device_rows += [tiles[i:i + HOUSE_COLUMNS] for i in range(0, len(tiles), HOUSE_COLUMNS)]
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

    def _lay_out_rooms(self, groups):
        """Rooms side by side, each with its title over its lights, as many on a
        line as fit HOUSE_COLUMNS lights; a big room goes on over the next line."""
        line, used = None, HOUSE_COLUMNS
        for area, members in groups:
            first = True
            while members:
                if used >= HOUSE_COLUMNS:
                    line = Gtk.Box(spacing=44, halign=Gtk.Align.START)
                    line.add_css_class("house-line")
                    self.device_box.append(line)
                    self.device_rows.append([])
                    used = 0
                chunk, members = members[:HOUSE_COLUMNS - used], members[HOUSE_COLUMNS - used:]
                room = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, hexpand=False)
                room.add_css_class("house-room")
                title = Gtk.Label(label=(area or self.t("house_no_area")) if first else "", xalign=0)
                title.add_css_class("area-title")
                room.append(title)
                row = Gtk.Box(spacing=20)
                for device in chunk:
                    tile = DeviceTile(device, self.t, self.svg_icon, self.on_device)
                    tile.area.set_visible(False)   # the room's title says it already
                    tile.set_size_request(DEVICE_WIDTH, -1)
                    tile.set_hexpand(False)   # its labels would stretch it over the line
                    row.append(tile)
                    self.device_tiles.append(tile)
                    self.device_rows[-1].append(tile)
                room.append(row)
                line.append(room)
                used += len(chunk)
                first = False

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

    def open_light(self, tile):
        """Hold Ⓐ (or Ⓨ) on a light: its brightness, colour temperature and colour,
        each as far as the light supports it."""
        device = tile.device
        box = self.dialog_box(device["name"])
        box.add_css_class("light-panel")
        rows = []
        level = {"pct": device.get("brightness") or (0 if not device["on"] else 100)}

        def call(**values):
            entity = device["entity"]
            self._house_call(lambda cfg, post: home_assistant.set_light(cfg, entity, post, **values))

        def line(title, widgets):
            row = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
            label = Gtk.Label(label=title, xalign=1)
            label.add_css_class("light-row-title")
            label.set_size_request(220, -1)
            row.append(label)
            for w in widgets:
                row.append(w)
            box.append(row)

        value = Gtk.Label()
        value.add_css_class("brightness-value")
        self.brightness_value = value

        def show():
            value.set_label(f"{level['pct']}%" if level["pct"] else self.t("dev_off_light"))

        def change(pct):
            level["pct"] = max(0, min(100, pct))
            show()
            tile.update({**tile.device, "on": level["pct"] > 0, "brightness": level["pct"] or None})
            p = level["pct"]
            self._house_call(lambda cfg, post: home_assistant.set_brightness(cfg, device["entity"], p, post))

        def turned_on():
            tile.update({**tile.device, "on": True})

        focus = None
        if device.get("dimmable"):
            minus = self.dialog_button("−", lambda: change((level["pct"] or 0) - BRIGHTNESS_STEP))
            plus = self.dialog_button("+", lambda: change((level["pct"] or 0) + BRIGHTNESS_STEP))
            for b in (minus, plus):
                b.add_css_class("brightness-step")
            value.set_size_request(200, -1)
            line(self.t("light_brightness"), [minus, value, plus])
            rows.append([minus, plus])
            focus = plus
            show()

        if device.get("temperature"):
            temps = []
            for kelvin in TEMPERATURES:
                if not device["min_kelvin"] <= kelvin <= device["max_kelvin"]:
                    continue
                b = self.dialog_button(f"{kelvin} K", lambda k=kelvin: (
                    turned_on(), call(color_temp_kelvin=k), self._mark(temps, k)))
                b.add_css_class("light-choice")
                b.add_css_class("kelvin-" + ("warm" if kelvin < 3300 else "neutral" if kelvin < 5000 else "cool"))
                b.value = kelvin
                temps.append(b)
            if temps:
                current = device.get("kelvin")
                if current:
                    self._mark(temps, min((b.value for b in temps), key=lambda k: abs(k - current)))
                line(self.t("light_temperature"), temps)
                rows.append(temps)

        if device.get("color"):
            swatches = []
            for name, hs in COLORS:
                b = Gtk.Button()
                b.add_css_class("color-swatch")
                b.add_css_class(f"color-{name}")
                b.set_focus_on_click(False)
                b.update_property([Gtk.AccessibleProperty.LABEL], [self.t(f"color_{name}")])
                b.value = name
                b.connect("clicked", lambda _b, n=name, v=hs: (
                    turned_on(), call(hs_color=list(v)), self._mark(swatches, n)))
                swatches.append(b)
            if device.get("hs"):
                h, sat = device["hs"]
                nearest = min(COLORS, key=lambda c: min(abs(c[1][0] - h), 360 - abs(c[1][0] - h))
                              + abs(c[1][1] - sat) / 4)
                self._mark(swatches, nearest[0])
            line(self.t("light_color"), swatches)
            rows.append(swatches)

        on_off = self.dialog_button(self.t("turn_off") if device["on"] else self.t("turn_on"),
                                    lambda: (self.pop_overlay(), self.on_device(tile)))
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        end = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        end.append(on_off)
        end.append(close)
        box.append(end)
        rows.append([on_off, close])
        self.push_overlay(box, rows, focus=focus or rows[0][0])

    open_brightness = open_light   # its first name

    @staticmethod
    def _mark(buttons, value):
        for b in buttons:
            (b.add_css_class if b.value == value else b.remove_css_class)("selected")

    def can_hold(self):
        """Is Ⓐ on something that does more when held (a light with settings)?"""
        focused = self.win.get_focus()
        return (not self.overlays and isinstance(focused, DeviceTile)
                and focused.device["domain"] == "light" and focused.device["available"]
                and bool(focused.device.get("dimmable") or focused.device.get("color")
                         or focused.device.get("temperature")))

    def long_press(self):
        if self.can_hold():
            self.open_light(self.win.get_focus())

    # --- timers and scrolling --------------------------------------------------------------

    def _home_tick(self):
        if self.win.is_active():
            self.update_media()
            if not self.overlays:
                self.update_house()
        return True

    def _focus_moved(self, *_):
        """Scroll so the focused row shows: the top (recently added and the apps)
        for anything above the house; in the house, the apps' row just above it."""
        focused = self.win.get_focus()
        if focused is None or self.overlays or not focused.is_ancestor(self.content):
            return
        if isinstance(focused, TabButton):
            self.select_tab(focused.tab)
        elif hasattr(focused, "app") and focused.is_ancestor(self.grid):
            self.set_context(self.context_of(focused.app))
        in_house = focused.is_ancestor(self.house_section) or focused.is_ancestor(self.forecast_section)
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
