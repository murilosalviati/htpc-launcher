# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""The screen's mode through Mutter's DisplayConfig (GNOME on Wayland), over D-Bus.

Modes are applied "temporary" (method 1): it takes effect at once, without
GNOME's "keep these display settings?" confirmation, and is not saved. The
mode GNOME keeps (~/.config/monitors.xml) stays the default the launcher goes
back to.
"""

import logging
import os
import threading
import xml.etree.ElementTree as ET

from ..base import Display, DisplayMode

log = logging.getLogger("htpc")

BUS = "org.gnome.Mutter.DisplayConfig"
PATH = "/org/gnome/Mutter/DisplayConfig"
TEMPORARY = 1


def _plain(v):
    return v[1] if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) else v


def saved_modes(path=None):
    """{connector: (width, height, rate)} from GNOME's saved configurations."""
    path = path or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                                "monitors.xml")
    found = {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return found
    for monitor in root.iter("monitor"):
        connector = monitor.findtext("monitorspec/connector")
        mode = monitor.find("mode")
        if connector and mode is not None:
            try:
                found.setdefault(connector, (int(mode.findtext("width")), int(mode.findtext("height")),
                                             float(mode.findtext("rate"))))
            except (TypeError, ValueError):
                continue
    return found


class MutterDisplay(Display):
    def __init__(self, bus="SESSION", monitors_xml=None):
        self.bus = bus
        self.monitors_xml = monitors_xml
        self._conn = None
        self._lock = threading.Lock()

    def _call(self, method, signature=None, body=()):
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection
        from jeepney.wrappers import unwrap_msg
        with self._lock:
            try:
                if self._conn is None:
                    self._conn = open_dbus_connection(bus=self.bus)
                msg = new_method_call(DBusAddress(PATH, bus_name=BUS, interface=BUS), method, signature, body)
                return unwrap_msg(self._conn.send_and_get_reply(msg, timeout=5))
            except (ConnectionError, OSError):
                self._conn = None
                raise

    def _state(self):
        serial, monitors, logical, _props = self._call("GetCurrentState")
        return serial, monitors, logical

    @staticmethod
    def _main_connector(monitors, logical):
        for lm in logical:
            if lm[4] and lm[5]:     # primary
                return lm[5][0][0]
        return monitors[0][0][0] if monitors else None

    def modes(self):
        _serial, monitors, logical = self._state()
        connector = self._main_connector(monitors, logical)
        for spec, modes, _props in monitors:
            if spec[0] != connector:
                continue
            out = []
            for mode_id, w, h, rate, _pref, _scales, props in modes:
                out.append(DisplayMode(mode_id, int(w), int(h), float(rate),
                                       current=bool(_plain(props.get("is-current", False)))))
            return out
        return []

    def default_mode(self):
        try:
            _serial, monitors, logical = self._state()
        except Exception as e:  # noqa: BLE001
            log.debug("display: %s", e)
            return None
        connector = self._main_connector(monitors, logical)
        saved = saved_modes(self.monitors_xml).get(connector)
        modes = self.modes()
        if saved:
            w, h, rate = saved
            same = [m for m in modes if m.width == w and m.height == h]
            if same:
                return min(same, key=lambda m: abs(m.refresh - rate))
        for spec, mlist, _props in monitors:   # nothing saved: the monitor's preferred mode
            if spec[0] == connector:
                for mode_id, w, h, rate, _pref, _scales, props in mlist:
                    if _plain(props.get("is-preferred", False)):
                        return DisplayMode(mode_id, int(w), int(h), float(rate))
        return next((m for m in modes if m.current), None)

    def apply(self, mode):
        serial, monitors, logical = self._state()
        connector = self._main_connector(monitors, logical)
        current_ids, scales = {}, {}
        for spec, modes, _props in monitors:
            for mode_id, _w, _h, _rate, _pref, supported, props in modes:
                if _plain(props.get("is-current", False)):
                    current_ids[spec[0]] = mode_id
                if mode_id == mode.id and spec[0] == connector:
                    scales[connector] = list(supported)
        if connector not in scales:
            raise RuntimeError(f"{mode.id} is not a mode of {connector}")
        config = []
        for x, y, scale, transform, primary, specs, _props in logical:
            monitors_out = []
            for spec in specs:
                mode_id = mode.id if spec[0] == connector else current_ids.get(spec[0])
                monitors_out.append((spec[0], mode_id, {}))
            if any(spec[0] == connector for spec in specs):
                supported = scales[connector]
                if supported and not any(abs(scale - s) < 0.01 for s in supported):
                    scale = min(supported, key=lambda s: abs(s - 1.0))
            config.append((x, y, float(scale), transform, primary, monitors_out))
        self._call("ApplyMonitorsConfig", "uua(iiduba(ssa{sv}))a{sv}", (serial, TEMPORARY, config, {}))
        log.info("display: %s", mode.label())
