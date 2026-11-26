# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The screensaver (mixed into the Launcher class).

After a few minutes with nobody touching the gamepad or the keyboard while the
launcher is in front, the screen shows the pictures of the films and series in
the row above the apps, one after the other, with a big clock, the date and the
weather. Any button brings the launcher back; that press does nothing else.

Settings → Screensaver chooses the wait (or Off); in apps.json it is
"screensaver_minutes" (0 = off).
"""

import time

from gi.repository import Gdk, GLib, Gtk, Pango

from htpc import jellyfin
from background import in_background

DEFAULT_MINUTES = 5
CHOICES = (0, 2, 5, 10, 30)       # minutes offered in Settings (0: off)
CHECK_S = 10                      # how often the wait is checked
SLIDE_S = 12                      # each picture stays this long
FADE_MS = 1500
TABS = ("resume", "explore", "movies", "series")   # where the pictures come from


class ScreensaverMixin:

    def saver_minutes(self):
        minutes = self.cfg.get("screensaver_minutes", DEFAULT_MINUTES)
        return minutes if isinstance(minutes, (int, float)) and minutes >= 0 else DEFAULT_MINUTES

    def start_screensaver_timer(self):
        self.last_input = time.monotonic()
        self.saver = None
        GLib.timeout_add_seconds(CHECK_S, self._saver_check)

    def wake(self):
        """Something was pressed. Returns True when it only closed the screensaver
        (the press must do nothing else)."""
        self.last_input = time.monotonic()
        if self.saver is None:
            return False
        self.hide_screensaver()
        return True

    def pad_connected(self):
        """A gamepad was turned on: someone is about to use the launcher. The
        screensaver closes and the home screen comes back at its start."""
        self.last_input = time.monotonic()
        if self.saver is not None:
            self.hide_screensaver()
            self.go_home()

    def _saver_check(self):
        minutes = self.saver_minutes()
        if (minutes and self.saver is None and self.win.is_active() and not self.overlays
                and time.monotonic() - self.last_input >= minutes * 60):
            self.show_screensaver()
        return True

    # --- showing it --------------------------------------------------------------------------

    def _saver_items(self):
        seen, items = set(), []
        for tab in TABS:
            for item in self.media.get(tab, []):
                url = item.get("backdrop")
                if url and url not in seen:
                    seen.add(url)
                    items.append(item)
        return items

    def show_screensaver(self):
        root = Gtk.Overlay()
        root.add_css_class("saver")
        root.set_can_target(False)
        self.saver_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                                     transition_duration=FADE_MS, hexpand=True, vexpand=True)
        root.set_child(self.saver_stack)
        shade = Gtk.Box(hexpand=True, vexpand=True)
        shade.add_css_class("saver-shade")
        root.add_overlay(shade)

        corner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                         halign=Gtk.Align.START, valign=Gtk.Align.END)
        corner.add_css_class("saver-corner")
        self.saver_title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=40)
        self.saver_title.add_css_class("saver-title")
        self.saver_clock = Gtk.Label(xalign=0)
        self.saver_clock.add_css_class("saver-clock")
        self.saver_date = Gtk.Label(xalign=0)
        self.saver_date.add_css_class("saver-date")
        for w in (self.saver_title, self.saver_clock, self.saver_date):
            corner.append(w)
        root.add_overlay(corner)

        self.saver = root
        self.saver_items = self._saver_items()
        self.saver_index = -1
        self.overlay.add_overlay(root)
        self._saver_tick()
        self._saver_next()
        self.saver_timers = [GLib.timeout_add_seconds(1, self._saver_tick),
                             GLib.timeout_add_seconds(SLIDE_S, self._saver_next)]

    def hide_screensaver(self):
        if self.saver is None:
            return
        for source in self.saver_timers:
            GLib.source_remove(source)
        self.overlay.remove_overlay(self.saver)
        self.saver = None

    def _saver_tick(self):
        if self.saver is None:
            return False
        self.saver_clock.set_label(self.time_label.get_label())
        date = self.date_label.get_label()
        c = self.conditions if self.cfg.get("weather") else None
        self.saver_date.set_label(f"{date}  •  {c.temperature}°" if c else date)
        return True

    def _saver_next(self):
        if self.saver is None:
            return False
        if not self.saver_items:
            self.saver_title.set_label("")
            return True
        self.saver_index = (self.saver_index + 1) % len(self.saver_items)
        item = self.saver_items[self.saver_index]
        url = item["backdrop"]

        def show(texture):
            if self.saver is None:
                return
            picture = Gtk.Picture(can_shrink=True, hexpand=True, vexpand=True)
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_paintable(texture)
            old = self.saver_stack.get_visible_child()
            self.saver_stack.add_child(picture)
            self.saver_stack.set_visible_child(picture)
            self.saver_title.set_label(item["title"])
            if old is not None:
                GLib.timeout_add(FADE_MS + 100, lambda: (old.get_parent() and self.saver_stack.remove(old), False)[1])

        texture = self.textures.get(url)
        if texture is not None:
            show(texture)
            return True
        cfg, get = dict(self.cfg), getattr(self, "jellyfin_get", None)

        def arrived(data):
            if isinstance(data, Exception):
                return
            try:
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
            except GLib.Error:
                return
            self.textures[url] = texture
            show(texture)

        in_background(lambda: jellyfin.image(cfg, url, get), arrived)
        return True
