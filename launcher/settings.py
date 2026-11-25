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
  * On-screen notices: turns the gamepad, battery and internet notices on or off;
  * Updates (a button at the bottom): the launcher, from GitHub releases, and
    the Flatpak apps;
  * Audio: picks the output (TV, headphones, a Bluetooth speaker...) and pairs
    Bluetooth headphones and speakers;
  * Gamepads: pairing over Bluetooth (or what to do without an adapter;
    paired gamepads can be forgotten from the same list) and the combos that bring the launcher back and close the
    app, recorded by holding the buttons (read by the controller service from
    the same apps.json);
  * Home Assistant: its own menu with the address and webhook id (typed on the
    on-screen keyboard), on/off, the footer's "Turn off TV" button, and a
    connection test. The controller service reads the same apps.json entry;
  * Close the launcher: quits it, after a confirmation (the guide button opens
    it again, through the controller service).

Everything is saved to apps.json. Like editor.py, this only uses the Launcher
instance and has nothing specific to an operating system.
"""

import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from htpc import __version__, home_assistant, shortcuts, updates, weather  # noqa: E402


def log(*args):
    print("[launcher]", *args, file=sys.stderr, flush=True)
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
        box.set_spacing(10)  # nine rows plus the buttons fit a 1080p screen
        box.add_css_class("settings-main")
        f = self.settings_fields = {
            "apps": self._field(self.t("settings_apps"), self._settings_apps, title_width=300),
            "background": self._field(self.t("background"), self.choose_background, title_width=300),
            "location": self._field(self.t("settings_location"), self._edit_location, title_width=300),
            "unit": self._field(self.t("settings_unit"), self._toggle_unit, title_width=300),
            "language": self._field(self.t("settings_language"), self._choose_language, title_width=300),
            "notifications": self._field(self.t("settings_notifications"), self._toggle_notifications,
                                         title_width=300),
            "audio": self._field(self.t("settings_audio"), self.open_audio, title_width=300),
            "shortcuts": self._field(self.t("settings_shortcuts"), self.open_shortcuts, title_width=300),
            "home_assistant": self._field(self.t("settings_ha"), self.open_home_assistant, title_width=300),
        }
        for w in f.values():
            box.append(w)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        updates_ = self.dialog_button(self.t("updates"), self.open_updates)
        quit_ = self.dialog_button(self.t("quit_launcher"), self._confirm_quit, danger=True)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        for b in (close, updates_, quit_):
            close_box.append(b)
        box.append(close_box)
        self.settings_quit = quit_
        self.settings_updates = updates_
        self.refresh_settings()
        self.push_overlay(box, [[w] for w in f.values()] + [[close, updates_, quit_]], focus=f.get(focus))

        def current_output(result):
            if not isinstance(result, Exception):
                self.audio_current = next((o.name for o in result if o.current), None)
                self.refresh_settings()

        self._bt(self.audio.outputs, current_output)

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
        f["notifications"].value.set_label(self.t("on" if self.cfg.get("notifications", True) else "off"))
        f["home_assistant"].value.set_label(self._ha_summary())
        f["audio"].value.set_label(getattr(self, "audio_current", None) or self.t("audio_value"))
        f["shortcuts"].value.set_label(shortcuts.combo_label(shortcuts.combos(self.cfg)["home"]))

    def _unit(self):
        unit = self.cfg.get("temperature_unit", "celsius")
        return unit if unit in UNITS else "celsius"

    def _confirm_quit(self):
        self.confirm(self.t("quit_title"), self.t("quit_text", home=shortcuts.combo_label(shortcuts.combos(self.cfg)["home"])), self.t("quit_launcher"), self.quit_launcher)

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

    # --- on-screen notices (shown by the controller service) ----------------------

    def _toggle_notifications(self):
        self.cfg["notifications"] = not self.cfg.get("notifications", True)
        self.save_config()
        self.refresh_settings()

    # --- audio output -----------------------------------------------------------------

    AUDIO_ROWS = 5

    def open_audio(self):
        box = self.dialog_box(self.t("settings_audio"), self.t("audio_text"))
        box.add_css_class("editor")
        box.add_css_class("settings")
        box.set_spacing(16)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        waiting = Gtk.Label(label=self.t("updates_checking"))
        waiting.add_css_class("dialog-text")
        listing.append(waiting)
        box.append(listing)
        pair = self._field(self.t("audio_pair"), lambda: self.open_pairing("audio"), title_width=420)
        box.append(pair)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        box.append(close_box)
        rows = [[pair], [close]]
        self.audio_menu = a = {"listing": listing, "rows": rows, "pair": pair, "close": close}
        self.push_overlay(box, rows, focus=pair)
        a["overlay"] = self.overlays[-1]
        self.refresh_audio()

    def refresh_audio(self):
        a = getattr(self, "audio_menu", None)
        if a is None:
            return
        self._bt(self.audio.outputs, lambda result: self._audio_listed(a, result))

    def _audio_listed(self, a, result):
        if self.audio_menu is not a:
            return
        listing = a["listing"]
        child = listing.get_first_child()
        while child is not None:
            listing.remove(child)
            child = listing.get_first_child()
        if isinstance(result, Exception) or not result:
            text = self.t("audio_none") if not isinstance(result, Exception) else \
                self.t("audio_error", error=self._reason(result))
            label = Gtk.Label(label=text)
            label.add_css_class("dialog-text")
            listing.append(label)
            a["rows"][:] = [[a["pair"]], [a["close"]]]
            return
        rows, focus = [], None
        for out in result[:self.AUDIO_ROWS]:
            title = out.name + ("  ·  Bluetooth" if out.bluetooth else "")
            b = self._field(title, lambda o=out: self._audio_chosen(o), title_width=520)
            b.value.set_label(self.t("audio_current") if out.current else "")
            b.audio_id = out.id
            listing.append(b)
            rows.append([b])
            if out.current:
                focus = b
                self.audio_current = out.name
        a["rows"][:] = rows + [[a["pair"]], [a["close"]]]
        if self.overlays and self.overlays[-1] is a.get("overlay") and focus is not None:
            focus.grab_focus()
        self.refresh_settings()

    def _audio_chosen(self, output):
        def done(result):
            if isinstance(result, Exception):
                self._message(self.t("audio_error", error=self._reason(result)))
            self.refresh_audio()

        self._bt(lambda: self.audio.set_output(output.id), done)

    # --- updates -------------------------------------------------------------------------

    def open_updates(self):
        box = self.dialog_box(self.t("updates"), self.t("updates_text", version=__version__))
        box.add_css_class("editor")
        box.add_css_class("settings")
        box.set_spacing(16)
        f = self.update_fields = {
            "launcher": self._field(self.t("updates_launcher"), self._update_launcher, title_width=300),
            "flatpak": self._field(self.t("updates_flatpak"), self._update_flatpak, title_width=300),
        }
        for w in f.values():
            w.value.set_label(self.t("updates_checking"))
            box.append(w)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        box.append(close_box)
        self.update_state = state = {"release": None, "flatpaks": None}
        self.push_overlay(box, [[w] for w in f.values()] + [[close]], focus=close)
        get = getattr(self, "updates_get", None)
        run = getattr(self, "updates_run", None)

        def release_arrived(result):
            if self.update_state is not state:
                return
            if isinstance(result, Exception):
                f["launcher"].value.set_label(self.t("updates_failed_check"))
            elif result and updates.is_newer(result["version"]):
                state["release"] = result
                f["launcher"].value.set_label(self.t("updates_new", version=result["version"]))
            else:
                f["launcher"].value.set_label(self.t("updates_none"))

        def flatpaks_arrived(result):
            if self.update_state is not state:
                return
            if isinstance(result, Exception):
                f["flatpak"].value.set_label(self.t("updates_failed_check"))
            else:
                state["flatpaks"] = result
                f["flatpak"].value.set_label(self.t("updates_apps", count=len(result)) if result
                                             else self.t("updates_none"))

        self._bt(lambda: updates.latest_release(get), release_arrived)
        self._bt(lambda: updates.flatpak_updates(run), flatpaks_arrived)

    def _update_launcher(self):
        release = (getattr(self, "update_state", None) or {}).get("release")
        if not release:
            return
        self.confirm(self.t("updates_install_title", version=release["version"]),
                     self.t("updates_install_text"), self.t("updates_install"),
                     lambda: self._install_release(release), danger=False)

    def _busy(self, text):
        box = self.dialog_box(text, self.t("updates_wait"))
        waiting = {"gone": False}
        self.push_overlay(box, [[]], cancel=lambda: waiting.update(gone=True))
        top = self.overlays[-1]

        def close():
            if not waiting["gone"] and self.overlays and self.overlays[-1] is top:
                self.pop_overlay()
        return close

    def _start_task(self, name):
        """True if the long task `name` may start now (it isn't running already)."""
        running = self.__dict__.setdefault("tasks_running", set())
        if name in running:
            log(name, "is already running")
            return False
        running.add(name)
        return True

    def _end_task(self, name):
        self.__dict__.setdefault("tasks_running", set()).discard(name)

    def _install_release(self, release):
        if not self._start_task("install"):
            return
        done_busy = self._busy(self.t("updates_installing", version=release["version"]))
        fetch = getattr(self, "updates_fetch", None)
        run = getattr(self, "updates_run", None)

        def done(result):
            self._end_task("install")
            done_busy()
            if isinstance(result, Exception):
                self._message(self.t("updates_install_failed"), self._reason(result))
                return
            note = self.t("updates_relogin") if result["extension_changed"] else ""
            self.confirm(self.t("updates_installed", version=result["version"]),
                         (self.t("updates_restart_text") + " " + note).strip(),
                         self.t("updates_restart_now"), self.restart_launcher, danger=False)

        self._bt(lambda: updates.install_release(release, fetch=fetch, run=run), done)

    def restart_launcher(self):
        """Start a new launcher (the updated one) and quit this one."""
        log("restarting the launcher")
        self._spawn(["systemd-run", "--user", "--collect", "-p", "KillMode=process",
                     "sh", "-c", "sleep 2; exec gtk-launch htpc-launcher"])
        self.quit_launcher()

    def _update_flatpak(self):
        apps = (getattr(self, "update_state", None) or {}).get("flatpaks")
        if not apps:
            return
        names = ", ".join(name for _id, name in apps[:6]) + ("…" if len(apps) > 6 else "")
        self.confirm(self.t("updates_apps_title", count=len(apps)), names, self.t("updates_install"),
                     self._run_flatpak_update, danger=False)

    def _run_flatpak_update(self):
        if not self._start_task("flatpak"):
            return
        done_busy = self._busy(self.t("updates_updating_apps"))
        run = getattr(self, "updates_run", None)

        def done(result):
            self._end_task("flatpak")
            done_busy()
            if isinstance(result, Exception):
                self._message(self.t("updates_install_failed"), self._reason(result))
                return
            state = getattr(self, "update_state", None)
            if state is not None:
                state["flatpaks"] = []
                self.update_fields["flatpak"].value.set_label(self.t("updates_none"))
            self._message(self.t("updates_apps_done"))

        self._bt(lambda: updates.flatpak_update(run), done)

    # --- pairing gamepads over Bluetooth -------------------------------------------------

    PAIRING_REFRESH_MS = 2000
    PAIRING_ROWS = 5

    def _bt(self, job, done):
        """Run a Bluetooth call off the UI thread; done(result or exception) on the main loop."""
        def work():
            try:
                result = job()
            except Exception as e:  # noqa: BLE001 - shown to the user
                result = e
            GLib.idle_add(lambda: (done(result), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def open_pairing(self, kind="gamepad"):
        """kind: "gamepad" or "audio" (headphones, speakers): what the list shows."""
        if getattr(self, "pairing", None) is not None or not self._start_task("bluetooth"):
            return
        done_busy = self._busy(self.t("pairing_checking"))

        def started(result):
            self._end_task("bluetooth")
            done_busy()
            if result is False:
                self._message(self.t("pairing_no_adapter"), self.t("pairing_no_adapter_text"))
            elif isinstance(result, Exception):
                self._message(self.t("pairing_error", error=self._reason(result)))
            else:
                self._show_pairing(kind)

        def start():
            if not self.bluetooth.available():
                return False
            self.bluetooth.start_search()
            return True

        self._bt(start, started)

    def _show_pairing(self, kind="gamepad"):
        if kind == "audio":
            box = self.dialog_box(self.t("pairing_audio_title"), self.t("pairing_audio_how"))
        else:
            box = self.dialog_box(self.t("pairing_title"), self.t("pairing_how"))
        box.add_css_class("editor")
        box.add_css_class("settings")
        box.set_spacing(16)
        status = Gtk.Label(label=self.t("pairing_searching"))
        status.add_css_class("dialog-text")
        box.append(status)
        listing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(listing)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        box.append(close_box)
        rows = [[close]]
        p = self.pairing = {"kind": kind, "listing": listing, "rows": rows, "close": close, "shown": None,
                            "timer": 0, "busy": False, "box": box}

        def stop():
            if p["timer"]:
                GLib.source_remove(p["timer"])
                p["timer"] = 0
            if self.pairing is p:
                self.pairing = None
            threading.Thread(target=self.bluetooth.stop_search, daemon=True).start()

        self.push_overlay(box, rows, focus=close, cancel=stop)
        p["overlay"] = self.overlays[-1]
        close.connect("clicked", lambda _b: stop())
        self._pairing_refresh()
        p["timer"] = GLib.timeout_add(self.PAIRING_REFRESH_MS, self._pairing_refresh)

    def _pairing_refresh(self):
        p = getattr(self, "pairing", None)
        if p is None:
            return False
        if not p["busy"]:
            self._bt(self.bluetooth.devices, lambda result: self._pairing_list(p, result))
        return True

    def _pairing_list(self, p, result):
        if self.pairing is not p or isinstance(result, Exception):
            return
        if p.get("kind") == "audio":
            wanted = (lambda d: d.audio)
        else:   # gamepads, keyboards and mice
            wanted = (lambda d: d.kind in ("gamepad", "keyboard", "mouse"))
        pads = [d for d in result if wanted(d) and (d.paired or d.has_name)][:self.PAIRING_ROWS]
        shown = [(d.address, d.name, d.paired, d.connected, d.kind) for d in pads]
        if shown == p["shown"]:
            return
        p["shown"] = shown
        focused = self.win.get_focus()
        focused_address = getattr(focused, "bt_address", None)
        listing = p["listing"]
        child = listing.get_first_child()
        while child is not None:
            listing.remove(child)
            child = listing.get_first_child()
        new_rows, focus = [], None
        for d in pads:
            if d.paired:
                state = self.t("pairing_connected" if d.connected else "pairing_paired")
                action = (lambda d=d: self._pairing_forget(d))
            else:
                state = self.t("pairing_found")
                action = (lambda d=d: self._pairing_pair(d))
            kind_label = self.t("bt_kind_" + d.kind) if d.kind in ("keyboard", "mouse") else ""
            b = self._field(d.name + (f"  ·  {kind_label}" if kind_label else ""), action, title_width=380)
            b.value.set_label(state)
            b.bt_address = d.address
            listing.append(b)
            new_rows.append([b])
            if d.address == focused_address:
                focus = b
        p["rows"][:] = new_rows + [[p["close"]]]
        if not self.overlays or self.overlays[-1] is not p.get("overlay"):
            return   # a message is on top: leave its focus alone
        if focus is not None:
            focus.grab_focus()
        elif focused_address is not None or focused is None or focused.get_root() is None:
            (new_rows[0][0] if new_rows else p["close"]).grab_focus()

    def _pairing_pair(self, device):
        p = self.pairing
        if p is None or p["busy"]:
            return
        p["busy"] = True
        box = self.dialog_box(self.t("pairing_busy", name=device.name))
        waiting = {"gone": False}
        self.push_overlay(box, [[]], cancel=lambda: waiting.update(gone=True))
        top = self.overlays[-1]

        def done(result):
            p["busy"] = False
            if not waiting["gone"] and self.overlays and self.overlays[-1] is top:
                self.pop_overlay()   # "Pairing…"
            p["shown"] = None    # redraw the list with the new state
            if isinstance(result, Exception):
                self._message(self.t("pairing_failed", name=device.name, error=self._reason(result)))
            else:
                self._message(self.t("pairing_done", name=device.name))
                if getattr(self, "audio_menu", None) is not None:
                    GLib.timeout_add(2500, lambda: (self.refresh_audio(), False)[1])

        self._bt(lambda: self.bluetooth.pair(device.address), done)

    def _pairing_forget(self, device):
        def forget():
            p = self.pairing
            if p is not None:
                p["shown"] = None

            def done(result):
                if isinstance(result, Exception):
                    self._message(self.t("pairing_error", error=self._reason(result)))

            self._bt(lambda: self.bluetooth.forget(device.address), done)

        self.confirm(self.t("pairing_forget_title", name=device.name), self.t("pairing_forget_text"),
                     self.t("pairing_forget"), forget)

    # --- gamepad shortcuts --------------------------------------------------------------

    RECORD_HOLD_MS = 2000     # hold the buttons this long to record them
    RECORD_GIVE_UP_S = 20     # nothing recorded after this: close the box

    def open_shortcuts(self, focus=None):
        box = self.dialog_box(self.t("settings_shortcuts"))
        box.add_css_class("editor")
        box.add_css_class("settings")
        box.set_spacing(16)
        f = self.shortcut_fields = {
            "pairing": self._field(self.t("settings_pairing"), self.open_pairing, title_width=300),
            "home": self._field(self.t("shortcut_home"), lambda: self.record_shortcut("home"), title_width=300),
            "close": self._field(self.t("shortcut_close"), lambda: self.record_shortcut("close"), title_width=300),
            "volume": self._field(self.t("shortcut_volume"),
                                  lambda: self._message(self.t("shortcut_volume"), self.t("shortcut_volume_text")),
                                  title_width=300),
            "reset": self._field(self.t("shortcuts_reset"), self._reset_shortcuts, title_width=300),
        }
        for w in f.values():
            box.append(w)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        box.append(close_box)
        self.refresh_shortcuts()
        self.push_overlay(box, [[w] for w in f.values()] + [[close]], focus=f.get(focus))

    def refresh_shortcuts(self):
        current = shortcuts.combos(self.cfg)
        f = getattr(self, "shortcut_fields", None)
        if f:
            f["pairing"].value.set_label(self.t("pairing_value"))
            f["home"].value.set_label(shortcuts.combo_label(current["home"]))
            f["close"].value.set_label(shortcuts.combo_label(current["close"]))
            f["volume"].value.set_label(self.t("shortcut_volume_value"))
            d = shortcuts.DEFAULT_COMBOS
            f["reset"].value.set_label(self.t("shortcuts_reset_value", home=shortcuts.combo_label(d["home"]),
                                              close=shortcuts.combo_label(d["close"])))
        if not self.editing:
            self.hint.set_label(self.hint_text())
        self.refresh_settings()

    def _save_combo(self, name, combo):
        current = shortcuts.combos(self.cfg)
        current[name] = frozenset(combo)
        saved = {k: [b for b in shortcuts.COMBO_BUTTONS if b in v] for k, v in current.items()
                 if v != shortcuts.DEFAULT_COMBOS[k]}
        if saved:
            self.cfg["shortcuts"] = saved
        else:
            self.cfg.pop("shortcuts", None)
        self.save_config()
        self.refresh_shortcuts()

    def _reset_shortcuts(self):
        if self.cfg.pop("shortcuts", None) is not None:
            self.save_config()
        self.refresh_shortcuts()

    def record_shortcut(self, name):
        """Hold the buttons of the new combo; holding B alone cancels."""
        box = self.dialog_box(self.t("record_title"), self.t("record_text"))
        live = Gtk.Label(label=self.t("record_waiting"))
        live.add_css_class("record-live")
        box.append(live)
        state = {"held": {}, "timer": 0, "give_up": 0}

        def held():
            out = set()
            for buttons in state["held"].values():
                out |= buttons
            return out

        def stop_timer():
            if state["timer"]:
                GLib.source_remove(state["timer"])
                state["timer"] = 0

        def cleanup():
            stop_timer()
            if state["give_up"]:
                GLib.source_remove(state["give_up"])
                state["give_up"] = 0
            if self.navigator.capture is capture:
                self.navigator.capture = None

        def finish(combo):
            cleanup()
            self.pop_overlay()
            if combo:
                self._combo_recorded(name, combo)
            return False

        def held_long_enough():
            state["timer"] = 0
            now = held()
            if now == {"b"}:
                return finish(None)
            if len(now) >= 2:
                return finish(frozenset(now))
            return False

        def capture(ev):
            if ev.kind == "disconnected":
                state["held"].pop(ev.device, None)
            else:
                buttons = state["held"].setdefault(ev.device, set())
                (buttons.add if ev.value else buttons.discard)(ev.name)
            now = held()
            live.set_label(shortcuts.combo_label(now & set(shortcuts.COMBO_BUTTONS)) or self.t("record_waiting"))
            stop_timer()
            if now == {"b"} or len(now) >= 2:
                state["timer"] = GLib.timeout_add(self.RECORD_HOLD_MS, held_long_enough)

        self.record_capture = capture    # for the tests
        self.navigator.capture = capture
        state["give_up"] = GLib.timeout_add_seconds(self.RECORD_GIVE_UP_S, lambda: (state.update(give_up=0),
                                                                                    finish(None))[1])
        cancel = self.dialog_button(self.t("cancel"), lambda: finish(None))  # keyboard or mouse
        box.append(cancel)
        self.push_overlay(box, [[cancel]], focus=cancel, cancel=cleanup)

    def _combo_recorded(self, name, combo):
        other = shortcuts.combos(self.cfg)["close" if name == "home" else "home"]
        problem = shortcuts.combo_problem(combo, other)
        if problem == "bad_button":
            self._message(self.t("combo_bad_button"))
            return
        if problem == "volume":
            self._message(self.t("combo_volume", combo=shortcuts.combo_label(combo)))
            return
        if problem:
            self._message(self.t("combo_overlap", combo=shortcuts.combo_label(combo & set(shortcuts.COMBO_BUTTONS)),
                                 other=shortcuts.combo_label(other)))
            return
        box = self.dialog_box(self.t("record_use", combo=shortcuts.combo_label(combo)))
        buttons = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        use = self.dialog_button(self.t("use"), lambda: (self.pop_overlay(), self._save_combo(name, combo)))
        cancel = self.dialog_button(self.t("cancel"), self.pop_overlay)
        buttons.append(use)
        buttons.append(cancel)
        box.append(buttons)
        self.push_overlay(box, [[use, cancel]], focus=use)

    # --- Home Assistant ----------------------------------------------------------------

    def _ha(self):
        return self.cfg.get("home_assistant") or {}

    def _ha_set(self, **values):
        ha = dict(self._ha())
        for key, value in values.items():
            if value in (None, ""):
                ha.pop(key, None)
            else:
                ha[key] = value
        if ha:
            self.cfg["home_assistant"] = ha
        else:
            self.cfg.pop("home_assistant", None)
        self.save_config()
        self.btn_tv.set_visible(self.tv_button_enabled())
        self.refresh_home_assistant()
        self.refresh_settings()

    def _ha_summary(self):
        ha = self._ha()
        if not ha.get("url") or not ha.get("webhook_id"):
            return self.t("ha_not_set")
        if not ha.get("enabled", True):
            return self.t("off")
        host = ha["url"].split("://", 1)[-1].rstrip("/")
        return self.t("ha_on_at", host=host)

    def open_home_assistant(self, focus=None):
        box = self.dialog_box(self.t("settings_ha"))
        box.add_css_class("editor")
        box.add_css_class("settings")
        box.set_spacing(16)
        f = self.ha_fields = {
            "enabled": self._field(self.t("ha_enabled"), self._ha_toggle_enabled, title_width=300),
            "url": self._field(self.t("ha_url"), self._ha_edit_url, title_width=300),
            "webhook": self._field(self.t("ha_webhook"), self._ha_edit_webhook, title_width=300),
            "events": self._field(self.t("ha_events"), self._ha_edit_events, title_width=300),
            "token": self._field(self.t("ha_token"), lambda: self._message(self.t("ha_token"), self.t("ha_token_text")),
                                 title_width=300),
            "tv": self._field(self.t("ha_tv"), self._ha_choose_tv, title_width=300),
            "tv_button": self._field(self.t("settings_tv_button"), self._toggle_tv_button, title_width=300),
            "test": self._field(self.t("ha_test"), self._ha_test, title_width=300),
        }
        for w in f.values():
            box.append(w)
        close = self.dialog_button(self.t("close"), self.pop_overlay)
        close_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        close_box.add_css_class("editor-buttons")
        close_box.append(close)
        box.append(close_box)
        self.refresh_home_assistant()
        self.push_overlay(box, [[w] for w in f.values()] + [[close]], focus=f.get(focus))

    def refresh_home_assistant(self):
        f = getattr(self, "ha_fields", None)
        if not f:
            return
        ha = self._ha()
        f["enabled"].value.set_label(self.t("on" if ha.get("enabled", True) else "off"))
        f["url"].value.set_label(ha.get("url") or "—")
        f["webhook"].value.set_label(ha.get("webhook_id") or "—")
        f["events"].value.set_label(ha.get("events_webhook_id") or self.t("off"))
        f["token"].value.set_label(self.t("ha_token_set" if ha.get("token") else "ha_token_missing"))
        if not ha.get("token"):
            f["tv"].value.set_label(self.t("ha_tv_needs_token"))
        else:
            f["tv"].value.set_label(ha.get("tv_name") or ha.get("tv_entity") or self.t("ha_tv_none"))
        if not home_assistant.webhook_url(self.cfg):
            f["tv_button"].value.set_label(self.t("tv_button_needs_ha"))
        else:
            f["tv_button"].value.set_label(self.t("on" if self.cfg.get("tv_off_button", False) else "off"))
        f["test"].value.set_label(self.t("ha_test_value"))

    def _ha_toggle_enabled(self):
        self._ha_set(enabled=None if not self._ha().get("enabled", True) else False)

    def _ha_edit_url(self):
        self.keyboard(self.t("ha_url_title"), self._ha().get("url", "http://"), self._ha_url_typed,
                      note=self.t("ha_url_note"), capitalize=False, extra=":/_")

    def _ha_url_typed(self, text):
        text = text.replace(" ", "").rstrip("/")
        if text in ("", "http:", "https:"):
            self._ha_set(url=None)
        elif not text.lower().startswith(("http://", "https://")):
            self._message(self.t("ha_bad_url"))
        else:
            self._ha_set(url=text)

    def _ha_edit_webhook(self):
        self.keyboard(self.t("ha_webhook_title"), self._ha().get("webhook_id", ""), self._ha_webhook_typed,
                      note=self.t("ha_webhook_note"), capitalize=False, extra=":/_")

    def _ha_webhook_typed(self, text):
        self._ha_set(webhook_id=text.replace(" ", "") or None)

    def _ha_edit_events(self):
        self.keyboard(self.t("ha_events_title"), self._ha().get("events_webhook_id", ""),
                      lambda text: self._ha_set(events_webhook_id=text.replace(" ", "") or None),
                      note=self.t("ha_events_note"), capitalize=False, extra=":/_")

    def _toggle_tv_button(self):
        if not home_assistant.webhook_url(self.cfg):
            self._message(self.t("tv_button_needs_ha_text"))
            return
        self.cfg["tv_off_button"] = not self.cfg.get("tv_off_button", False)
        self.save_config()
        self.btn_tv.set_visible(self.tv_button_enabled())
        self.refresh_home_assistant()

    def _ha_ask(self, job, done):
        """Run job() in a thread behind a "Calling Home Assistant…" box (with Cancel),
        then done(result) on the main loop; result is an exception if job failed."""
        box = self.dialog_box(self.t("ha_testing"))
        token = object()
        self.ha_request = token

        def give_up():
            self.ha_request = None

        cancel = self.dialog_button(self.t("cancel"), lambda: (give_up(), self.pop_overlay()))
        box.append(cancel)
        self.push_overlay(box, [[cancel]], focus=cancel, cancel=give_up)

        def arrived(result):
            if self.ha_request is token:
                self.ha_request = None
                self.pop_overlay()
                done(result)
            return False

        def work():
            try:
                result = job()
            except Exception as e:  # noqa: BLE001 - shown to the user
                result = e
            GLib.idle_add(arrived, result)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _reason(error):
        return str(getattr(error, "reason", None) or error)[:80]

    def _ha_test(self):
        url = home_assistant.webhook_url(self.cfg)
        if not url:
            self._message(self.t("tv_button_needs_ha_text"))
            return
        post = getattr(self, "ha_post", None) or home_assistant.http_post
        get = getattr(self, "ha_get", None)
        cfg = dict(self.cfg)

        def job():
            post(url, {"event": "test", "gamepad": "", "host": "launcher"})
            return home_assistant.fetch_tv_state(cfg, get) if home_assistant.api_ready(cfg) else False

        def done(result):
            if isinstance(result, Exception):
                self._message(self.t("ha_test_failed", error=self._reason(result)))
            elif result is False:  # no token or TV: only the webhook was tested
                self._message(self.t("ha_test_ok"))
            else:
                state = self.t({"on": "ha_tv_on", "off": "ha_tv_off"}.get(result, "ha_tv_unknown"))
                self._message(self.t("ha_test_ok") + " " + self.t("ha_tv_is", state=state))

        self._ha_ask(job, done)

    def _ha_choose_tv(self):
        ha = self._ha()
        if not ha.get("url") or not ha.get("token"):
            self._message(self.t("ha_token"), self.t("ha_token_text"))
            return
        get = getattr(self, "ha_get", None)
        cfg = dict(self.cfg)
        self._ha_ask(lambda: home_assistant.media_players(cfg, get), self._ha_players_arrived)

    def _ha_players_arrived(self, result):
        if isinstance(result, Exception):
            self._message(self.t("ha_list_failed", error=self._reason(result)))
            return
        if not result:
            self._message(self.t("ha_no_players"))
            return
        box = self.dialog_box(self.t("ha_choose_tv"))
        box.add_css_class("editor")
        rows, focus = [], None
        current = self._ha().get("tv_entity")
        for entity, name in result[:8]:
            b = self._field(name, lambda e=entity, n=name: self._ha_tv_chosen(e, n), title_width=380)
            b.value.set_label(entity)
            if entity == current:
                focus = b
            box.append(b)
            rows.append([b])
        self.push_overlay(box, rows, focus=focus)

    def _ha_tv_chosen(self, entity, name):
        self.pop_overlay()
        self._ha_set(tv_entity=entity, tv_name=name)

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

    def _message(self, text, body=None):
        box = self.dialog_box(text, body)
        ok = self.dialog_button(self.t("ok"), self.pop_overlay)
        box.append(ok)
        self.push_overlay(box, [[ok]], focus=ok)
