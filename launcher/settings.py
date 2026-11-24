# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The settings menu, opened by the gear in the footer.

  * Apps: enters edit mode (editor.py) to add, edit and remove shortcuts;
  * Background: the background color picker;
  * Weather location: a Brazilian CEP or a city name, typed on the on-screen
    keyboard. It is looked up once, confirmed on screen, and saved with its
    coordinates; empty hides the weather;
  * Temperature: °C or °F, switched with Ⓐ;
  * Language: rebuilds the screen in the chosen language right away;
  * Close the launcher: quits it, after a confirmation (the guide button opens
    it again, through the controller service).

Everything is saved to apps.json. Like editor.py, this only uses the Launcher
instance and has nothing specific to an operating system.
"""

import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from htpc import weather  # noqa: E402
from htpc.i18n import STRINGS, Translator  # noqa: E402

UNITS = {"celsius": "°C", "fahrenheit": "°F"}


class SettingsMixin:
    def settings_button(self):
        """The gear: opens the settings; in edit mode it reads "Done" and leaves it."""
        if self.editing:
            self.toggle_edit_mode()
        else:
            self.open_settings()

    # --- the menu ---------------------------------------------------------------------

    def open_settings(self, focus=None):
        box = self.dialog_box(self.t("settings"))
        box.add_css_class("editor")
        box.add_css_class("settings")
        f = self.settings_fields = {
            "apps": self._field(self.t("settings_apps"), self._settings_apps, title_width=300),
            "background": self._field(self.t("background"), self.choose_background, title_width=300),
            "location": self._field(self.t("settings_location"), self._edit_location, title_width=300),
            "unit": self._field(self.t("settings_unit"), self._toggle_unit, title_width=300),
            "language": self._field(self.t("settings_language"), self._choose_language, title_width=300),
        }
        for w in f.values():
            box.append(w)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        quit_ = self.dialog_button(self.t("quit_launcher"), self._confirm_quit, danger=True)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        close_box.append(quit_)
        box.append(close_box)
        self.settings_quit = quit_
        self.refresh_settings()
        self.push_overlay(box, [[w] for w in f.values()] + [[close, quit_]], focus=f.get(focus))

    def refresh_settings(self):
        f = getattr(self, "settings_fields", None)
        if not f:
            return
        f["apps"].value.set_label(self.t("apps_value"))
        f["background"].value.set_label(self.t(f"theme_{self.theme}"))
        place = self.cfg.get("weather")
        f["location"].value.set_label(place["name"] if place else self.t("weather_off"))
        f["unit"].value.set_label(UNITS[self._unit()])
        f["language"].value.set_label(self.t("language_name"))

    def _unit(self):
        unit = self.cfg.get("temperature_unit", "celsius")
        return unit if unit in UNITS else "celsius"

    def _confirm_quit(self):
        self.confirm(self.t("quit_title"), self.t("quit_text"), self.t("quit_launcher"), self.quit_launcher)

    def quit_launcher(self):
        self.gtk_app.quit()

    def _settings_apps(self):
        self.pop_overlay()
        self.toggle_edit_mode()

    # --- temperature unit ------------------------------------------------------------

    def _toggle_unit(self):
        self.cfg["temperature_unit"] = "fahrenheit" if self._unit() == "celsius" else "celsius"
        self.save_config()
        self.refresh_settings()
        self.conditions = None  # the old number is in the other unit
        self.update_weather()

    # --- language ---------------------------------------------------------------------

    def _choose_language(self):
        box = self.dialog_box(self.t("choose_language"))
        row, focus = [], None
        buttons = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        for code in STRINGS:
            b = self.dialog_button(Translator(code)("language_name"), lambda c=code: self._language_chosen(c))
            if code == self.cfg.get("language"):
                focus = b
            buttons.append(b)
            row.append(b)
        box.append(buttons)
        self.push_overlay(box, [row], focus=focus)

    def _language_chosen(self, code):
        while self.overlays:
            self.pop_overlay()
        if code != self.cfg.get("language"):
            self.cfg["language"] = code
            self.save_config()
            self.t = Translator(code)
            self.build_ui()
            self.refresh_top_bar()
        self.open_settings(focus="language")

    # --- weather location ------------------------------------------------------------

    def _edit_location(self):
        place = self.cfg.get("weather") or {}
        self.keyboard(self.t("location_title"), place.get("query", ""), self._location_typed,
                      note=self.t("location_note"))

    def _location_typed(self, text):
        if not text:
            if self.cfg.pop("weather", None) is not None:
                self.save_config()
                self.update_weather()
            self.refresh_settings()
            return
        box = self.dialog_box(self.t("searching"), text)
        token = object()
        self.location_search = token

        def give_up():  # the answer is ignored when it arrives
            self.location_search = None

        cancel = self.dialog_button(self.t("cancel"), lambda: (give_up(), self.pop_overlay()))
        box.append(cancel)
        self.push_overlay(box, [[cancel]], focus=cancel, cancel=give_up)
        language, fetch = self.cfg.get("language", "en"), self.weather_fetch

        def work():
            try:
                result = weather.find_place(text, language, fetch)
            except Exception as e:  # noqa: BLE001 - shown to the user below
                result = e
            GLib.idle_add(self._location_found, token, text, result)

        threading.Thread(target=work, daemon=True).start()

    def _location_found(self, token, text, result):
        if self.location_search is not token:
            return False
        self.location_search = None
        self.pop_overlay()  # "Looking it up…"
        if isinstance(result, weather.NotFound):
            self._message(self.t("place_not_found", query=text))
        elif isinstance(result, Exception):
            self._message(self.t("place_unreachable"))
        else:
            box = self.dialog_box(self.t("use_place", name=result.name))
            buttons = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
            use = self.dialog_button(self.t("use"), lambda: self._place_confirmed(text, result))
            cancel = self.dialog_button(self.t("cancel"), self.pop_overlay)
            buttons.append(use)
            buttons.append(cancel)
            box.append(buttons)
            self.push_overlay(box, [[use, cancel]], focus=use)
        return False

    def _place_confirmed(self, text, place):
        self.pop_overlay()
        self.cfg["weather"] = {"query": text, "name": place.name,
                               "latitude": place.latitude, "longitude": place.longitude}
        self.save_config()
        self.conditions = None
        self.update_weather()
        self.refresh_settings()

    def _message(self, text):
        box = self.dialog_box(text)
        ok = self.dialog_button(self.t("ok"), self.pop_overlay)
        box.append(ok)
        self.push_overlay(box, [[ok]], focus=ok)
