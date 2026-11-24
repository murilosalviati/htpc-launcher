# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Launcher edit mode: add, edit and remove app shortcuts.

Entered from the "Edit apps" button in the footer. There, Ⓐ on an app opens
the editor and Ⓐ on "+ Add" creates a new shortcut. The editor has three
fields:

  * Name: typed on the on-screen keyboard (or a real keyboard);
  * Application: picked from the installed apps (system and Flatpak
    .desktop files);
  * Icon: the app's own icon or an image from the icon folder
    (~/.local/share/htpc-launcher/app-icons).

Everything is saved to apps.json, which the controller service reads too.

This file does not import launcher.py: what it needs from there comes
through the Launcher class itself (app_icon, desktop_info, app_icons_dir...).
"""

import os
from pathlib import Path

import themes

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gio, Gtk, Pango  # noqa: E402

# Settings that only make sense for the shortcut's original application.
# If the shortcut is switched to another application, they are dropped.
APP_SPECIFIC_KEYS = ("extra_ids", "desktop", "close", "close_timeout", "on_resume",
                     "preferred_windows", "pause_on_home", "close_on_second_press")

ICON_EXTENSIONS = (".png", ".svg", ".jpg", ".jpeg", ".webp")


def _with_tilde(path):
    """Path with ~ instead of the home folder, as written in apps.json."""
    home = str(Path.home())
    path = str(path)
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


class EditorMixin:
    # --- entering and leaving edit mode -------------------------------------------

    def toggle_edit_mode(self):
        self.editing = not self.editing
        self.hint.set_label(self.t("hint_edit") if self.editing else self.t("hint_normal"))
        self.btn_background.set_visible(self.editing)
        if self.editing:
            self.hint.add_css_class("editing")
            self.btn_settings.label.set_label(self.t("done"))
        else:
            self.hint.remove_css_class("editing")
            self.btn_settings.label.set_label(self.t("edit_apps"))
        self.build_grid(focus=0 if self.cfg.get("apps") else -1)

    def new_app(self):
        self.edit_app(None)

    # --- editor -------------------------------------------------------------------------

    def edit_app(self, index):
        original = dict(self.cfg["apps"][index]) if index is not None else {}
        draft = {"name": original.get("name", "")}
        for k in ("id", "launch", "icon", *APP_SPECIFIC_KEYS):
            if k in original:
                draft[k] = original[k]
        self.editor = {"index": index, "original": original, "draft": draft}

        box = self.dialog_box(self.t("edit_app") if index is not None else self.t("new_app"))
        box.add_css_class("editor")
        self.editor_preview = Gtk.Image()
        self.editor_preview.set_pixel_size(112)
        box.append(self.editor_preview)

        self.field_name = self._field(self.t("field_name"), self._edit_name)
        self.field_app = self._field(self.t("field_app"), self._choose_app)
        self.field_icon = self._field(self.t("field_icon"), self._choose_icon)
        for f in (self.field_name, self.field_app, self.field_icon):
            box.append(f)

        self.editor_error = Gtk.Label(label="")
        self.editor_error.add_css_class("error")
        self.editor_error.set_visible(False)
        box.append(self.editor_error)

        buttons = [self.dialog_button(self.t("save"), self._save_app)]
        if index is not None:
            buttons.append(self.dialog_button(self.t("remove"), self._remove_app, danger=True))
        buttons.append(self.dialog_button(self.t("cancel"), self.pop_overlay))
        button_box = Gtk.Box(spacing=20, halign=Gtk.Align.CENTER)
        button_box.add_css_class("editor-buttons")
        for b in buttons:
            button_box.append(b)
        box.append(button_box)

        self._refresh_editor()
        rows = [[self.field_name], [self.field_app], [self.field_icon], buttons]
        # For a new shortcut, picking the app comes first (the name comes from it).
        self.push_overlay(box, rows, focus=self.field_app if index is None else self.field_name)

    def _field(self, title, action):
        b = Gtk.Button()
        b.add_css_class("field")
        b.set_focus_on_click(False)
        box = Gtk.Box(spacing=24)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("field-title")
        label.set_size_request(190, -1)
        b.value = Gtk.Label(label="", xalign=0, hexpand=True,
                            ellipsize=Pango.EllipsizeMode.END, max_width_chars=36)
        b.value.add_css_class("field-value")
        arrow = Gtk.Label(label="›")
        arrow.add_css_class("field-arrow")
        for w in (label, b.value, arrow):
            box.append(w)
        b.set_child(box)
        b.connect("clicked", lambda _b: action())
        return b

    def _describe_app(self, draft):
        for name in (draft.get("desktop"), f"{draft['id']}.desktop" if draft.get("id") else None):
            if name:
                info = self.desktop_info(name)
                if info:
                    return info.get_display_name()
        if draft.get("launch"):
            return " ".join(draft["launch"])
        return self.t("choose")

    def _refresh_editor(self):
        draft = self.editor["draft"]
        self.field_name.value.set_label(draft["name"] or self.t("unnamed"))
        self.field_app.value.set_label(self._describe_app(draft))
        icon = draft.get("icon")
        self.field_icon.value.set_label(Path(os.path.expanduser(icon)).name if icon else self.t("own_icon"))
        self.editor_preview.set_from_gicon(self.app_icon(draft))
        self.editor_preview.set_pixel_size(112)
        self.editor_error.set_visible(False)

    def _show_error(self, text):
        self.editor_error.set_label(text)
        self.editor_error.set_visible(True)

    def _save_app(self):
        draft = self.editor["draft"]
        if not draft.get("id") or not draft.get("launch"):
            self._show_error(self.t("error_no_app"))
            return
        if not draft["name"].strip():
            self._show_error(self.t("error_no_name"))
            return
        original, index = self.editor["original"], self.editor["index"]

        # Same app: keep whatever settings it had. A different app starts clean.
        base = dict(original) if draft["id"] == original.get("id") else {}
        for k in APP_SPECIFIC_KEYS:
            base.pop(k, None)
        app = {"name": draft["name"].strip(), "id": draft["id"]}
        if draft.get("icon"):
            app["icon"] = draft["icon"]
        app["launch"] = draft["launch"]
        for k, v in base.items():
            if k != "icon":  # the icon came from the draft (or was removed)
                app.setdefault(k, v)
        for k in APP_SPECIFIC_KEYS:
            if k in draft:
                app[k] = draft[k]

        apps = self.cfg.setdefault("apps", [])
        if index is None:
            apps.append(app)
            index = len(apps) - 1
        else:
            apps[index] = app
        self.save_config()
        self.pop_overlay()
        self.build_grid(focus=index)

    def _remove_app(self):
        index = self.editor["index"]
        name = self.cfg["apps"][index].get("name") or self.t("this_app")
        self.confirm(self.t("remove_title", name=name), self.t("remove_text"),
                     self.t("remove"), lambda: self._remove_confirmed(index))

    def _remove_confirmed(self, index):
        apps = self.cfg["apps"]
        del apps[index]
        self.save_config()
        self.pop_overlay()  # closes the editor (the confirmation already closed)
        self.build_grid(focus=min(index, len(apps) - 1) if apps else -1)

    # --- name: on-screen keyboard ---------------------------------------------------------

    def _edit_name(self):
        self.keyboard(self.t("keyboard_title"), self.editor["draft"]["name"], self._name_typed)

    def _name_typed(self, text):
        self.editor["draft"]["name"] = text
        self._refresh_editor()

    def keyboard(self, title, value, on_done):
        # Capitalize the first letter automatically, like a phone keyboard.
        state = {"text": value, "shift": not value}
        box = self.dialog_box(title)
        box.add_css_class("keyboard")
        display = Gtk.Label(label="", xalign=0)
        display.add_css_class("keyboard-display")
        box.append(display)

        letter_keys = []

        def refresh():
            display.set_label(state["text"] + "▏")
            for b in letter_keys:
                b.set_label(b.char.upper() if state["shift"] else b.char)

        def type_char(c):
            if state["shift"] and c.isalpha():
                c = c.upper()
                state["shift"] = False
            state["text"] += c
            refresh()

        def delete():
            state["text"] = state["text"][:-1]
            if not state["text"]:
                state["shift"] = True  # cleared everything: start capitalized again
            refresh()

        def toggle_shift():
            state["shift"] = not state["shift"]
            refresh()

        def done():
            self.pop_overlay()
            on_done(state["text"].strip())

        rows = []
        for row_text in self.t.raw("keyboard_rows"):
            row_box = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
            row = []
            for c in row_text:
                b = Gtk.Button(label=c)
                b.char = c
                b.add_css_class("key")
                b.set_focus_on_click(False)
                b.connect("clicked", lambda _b: type_char(_b.get_label()))
                letter_keys.append(b)
                row_box.append(b)
                row.append(b)
            box.append(row_box)
            rows.append(row)

        special = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        row = []
        for label, action, css in ((self.t("key_shift"), toggle_shift, "key-wide"),
                                   (self.t("key_space"), lambda: type_char(" "), "key-space"),
                                   (self.t("key_backspace"), delete, "key-wide"),
                                   (self.t("key_ok"), done, "key-ok")):
            b = Gtk.Button(label=label)
            b.add_css_class("key")
            b.add_css_class(css)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, a=action: a())
            special.append(b)
            row.append(b)
        box.append(special)
        rows.append(row)

        hint = Gtk.Label(label=self.t("keyboard_hint"))
        hint.add_css_class("dialog-text")
        box.append(hint)

        refresh()
        self.push_overlay(box, rows, focus=rows[1][0],
                          type=type_char, delete=delete, space=lambda: type_char(" "), enter=done)

    # --- application: list of installed apps ---------------------------------------------

    def _installed_apps(self):
        seen = {}
        for info in Gio.AppInfo.get_all():
            if isinstance(info, Gio.DesktopAppInfo) and info.should_show():
                seen[info.get_id()] = info
        # Flatpak apps, in case the session is not looking at their folder.
        for base in self.flatpak_exports:
            folder = base / "applications"
            if not folder.is_dir():
                continue
            for path in folder.glob("*.desktop"):
                if path.name in seen:
                    continue
                info = Gio.DesktopAppInfo.new_from_filename(str(path))
                if info and info.should_show():
                    seen[path.name] = info
        seen.pop(f"{self.launcher_id}.desktop", None)
        return sorted(seen.values(), key=lambda i: i.get_display_name().casefold())

    def _choose_app(self):
        infos = self._installed_apps()
        box = self.dialog_box(self.t("choose_app"))
        box.add_css_class("picker")

        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        rows, focus = [], None
        current = self.editor["draft"].get("id")
        for i in range(0, len(infos), 4):
            row_box = Gtk.Box(spacing=12, halign=Gtk.Align.START)
            row = []
            for info in infos[i:i + 4]:
                b = Gtk.Button()
                b.add_css_class("app-item")
                b.set_focus_on_click(False)
                b.set_size_request(280, -1)
                b.set_hexpand(False)
                inner = Gtk.Box(spacing=16)
                image = Gtk.Image.new_from_gicon(info.get_icon() or Gio.ThemedIcon.new("application-x-executable"))
                image.set_pixel_size(48)
                name = Gtk.Label(label=info.get_display_name(), xalign=0, hexpand=True,
                                 ellipsize=Pango.EllipsizeMode.END, width_chars=14, max_width_chars=14)
                inner.append(image)
                inner.append(name)
                b.set_child(inner)
                b.connect("clicked", lambda _b, info=info: self._app_chosen(info))
                if current and info.get_id() == f"{current}.desktop":
                    focus = b
                row_box.append(b)
                row.append(b)
            grid.append(row_box)
            rows.append(row)

        if not infos:
            empty = Gtk.Label(label=self.t("no_apps"))
            empty.add_css_class("dialog-text")
            box.append(empty)
            back = self.dialog_button(self.t("back"), self.pop_overlay)
            box.append(back)
            rows = [[back]]
        else:
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_size_request(1180, 560)
            scroller.set_child(grid)
            box.append(scroller)
        self.push_overlay(box, rows, focus=focus)

    def _app_chosen(self, info):
        draft, original = self.editor["draft"], self.editor["original"]
        desktop_id = info.get_id()
        app_id = desktop_id[:-len(".desktop")] if desktop_id.endswith(".desktop") else desktop_id
        for k in ("launch", *APP_SPECIFIC_KEYS):
            draft.pop(k, None)
        if app_id == original.get("id"):
            # Back to the app it had: keep its command and settings.
            for k in ("launch", *APP_SPECIFIC_KEYS):
                if k in original:
                    draft[k] = original[k]
        else:
            draft["launch"] = ["gio", "launch", info.get_filename()]
            draft["desktop"] = desktop_id
            wm_class = info.get_startup_wm_class()
            if wm_class:
                draft["extra_ids"] = [wm_class]
        draft["id"] = app_id
        if not draft["name"].strip():
            draft["name"] = info.get_display_name()
        self.pop_overlay()
        self._refresh_editor()

    # --- icon ---------------------------------------------------------------------------------

    def _choose_icon(self):
        draft = self.editor["draft"]
        without_icon = {k: v for k, v in draft.items() if k != "icon"}
        options = [(None, self.t("own_icon_short"), self.app_icon(without_icon))]
        folder = self.app_icons_dir
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.suffix.lower() in ICON_EXTENSIONS:
                    options.append((_with_tilde(path), path.stem,
                                    Gio.FileIcon.new(Gio.File.new_for_path(str(path)))))

        box = self.dialog_box(self.t("choose_icon"), self.t("icon_hint", path=_with_tilde(folder)))
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, halign=Gtk.Align.CENTER)
        rows, focus = [], None
        for i in range(0, len(options), 5):
            row_box = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
            row = []
            for value, label, gicon in options[i:i + 5]:
                b = Gtk.Button()
                b.add_css_class("icon-item")
                b.set_focus_on_click(False)
                inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
                image = Gtk.Image.new_from_gicon(gicon)
                image.set_pixel_size(96)
                name = Gtk.Label(label=label, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
                inner.append(image)
                inner.append(name)
                b.set_child(inner)
                b.connect("clicked", lambda _b, v=value: self._icon_chosen(v))
                if value == draft.get("icon"):
                    focus = b
                row_box.append(b)
                row.append(b)
            grid.append(row_box)
            rows.append(row)
        box.append(grid)
        self.push_overlay(box, rows, focus=focus)

    def _icon_chosen(self, value):
        draft = self.editor["draft"]
        if value:
            draft["icon"] = value
        else:
            draft.pop("icon", None)
        self.pop_overlay()
        self._refresh_editor()

    # --- background color ------------------------------------------------------------------

    def choose_background(self):
        """Theme picker. Moving the focus previews the color; Ⓐ keeps it, Ⓑ goes back to the saved one."""
        saved = self.theme
        box = self.dialog_box(self.t("choose_background"))
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, halign=Gtk.Align.CENTER)
        rows, focus, row = [], None, []
        row_box = None
        for i, theme_id in enumerate(themes.THEMES):
            if i % 3 == 0:
                row_box = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER)
                grid.append(row_box)
                row = []
                rows.append(row)
            b = Gtk.Button()
            b.add_css_class("swatch")
            b.set_focus_on_click(False)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            sample = Gtk.Box()
            sample.add_css_class("swatch-sample")
            sample.add_css_class(f"swatch-{theme_id}")
            sample.set_size_request(220, 110)
            name = Gtk.Label(label=self.t(f"theme_{theme_id}"))
            inner.append(sample)
            inner.append(name)
            b.set_child(inner)
            b.connect("clicked", lambda _b, tid=theme_id: self._background_chosen(tid))
            preview = Gtk.EventControllerFocus()
            preview.connect("enter", lambda _c, tid=theme_id: self.apply_theme(tid))
            b.add_controller(preview)
            if theme_id == saved:
                focus = b
            row_box.append(b)
            row.append(b)
        box.append(grid)
        self.push_overlay(box, rows, focus=focus, cancel=lambda: self.apply_theme(saved))

    def _background_chosen(self, theme_id):
        self.apply_theme(theme_id)
        self.cfg["background"] = theme_id
        self.save_config()
        self.pop_overlay()
