# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Fake GNOME extension and MPRIS player, to test the controller and launcher on a real D-Bus."""
import json
import threading

from jeepney import MessageType, new_error, new_method_return
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection

state = {
    "windows": [
        {"appId": "htpc-launcher", "ids": ["htpc-launcher"], "title": "Launcher", "pid": 0, "minimized": False},
        {"appId": "org.jellyfin.JellyfinDesktop", "ids": ["org.jellyfin.jellyfindesktop", "jellyfin"], "title": "Jellyfin", "pid": 0, "minimized": False},
        {"appId": "rocks.shy.VacuumTube", "ids": ["rocks.shy.vacuumtube", "vacuumtube"], "title": "YouTube", "pid": 0, "minimized": False},
        {"appId": "com.moonlight_stream.Moonlight", "ids": ["com.moonlight_stream.moonlight", "moonlight"], "title": "Moonlight", "pid": 0, "minimized": False},
        {"appId": "game", "ids": ["steam_app_1", "game"], "title": "Stubborn game", "pid": 0, "minimized": False, "stubborn": True},
    ],
    "focus": "org.jellyfin.JellyfinDesktop",
    "player": "Playing",
    "log": [],
}


def find(app):
    a = app.lower()
    return [w for w in state["windows"] if a in w["ids"] or w["appId"].lower() == a]


def shell():
    conn = open_dbus_connection(bus="SESSION")
    conn.send_and_get_reply(message_bus.RequestName("org.htpc.Launcher"))
    while True:
        m = conn.receive()
        if m.header.message_type != MessageType.method_call:
            continue
        name = m.header.fields[3]
        args = m.body
        state["log"].append((name, args))
        if name == "ListWindows":
            js = [dict(w, focused=(w["appId"] == state["focus"])) for w in state["windows"]]
            r = new_method_return(m, "s", (json.dumps(js),))
        elif name == "IsRunning":
            r = new_method_return(m, "b", (bool(find(args[0])),))
        elif name == "Close":
            ws = find(args[0])
            for w in ws:
                if not w.get("stubborn"):
                    state["windows"].remove(w)
            r = new_method_return(m, "u", (len(ws),))
        elif name in ("Activate", "ActivatePreferring"):
            ws = find(args[0])
            titles = args[1] if name == "ActivatePreferring" else []
            target = next((w for t in titles for w in ws if w["title"] == t), ws[0] if ws else None)
            if target:
                state["focus"] = target["appId"]
                state["activated"] = target["title"]
            r = new_method_return(m, "b", (target is not None,))
        elif name == "HidePointer":
            state["pointer_hidden"] = state.get("pointer_hidden", 0) + 1
            r = new_method_return(m, "b", (True,))
        elif name == "FullscreenOnOpen":
            state.setdefault("fullscreen", []).append(args[0])
            r = new_method_return(m, "u", (0,))
        elif name == "ShowLauncher":
            state["focus"] = "htpc-launcher"
            r = new_method_return(m, "b", (True,))
        else:
            r = new_error(m, "org.freedesktop.DBus.Error.UnknownMethod")
        conn.send(r)


def player():
    conn = open_dbus_connection(bus="SESSION")
    conn.send_and_get_reply(message_bus.RequestName("org.mpris.MediaPlayer2.jellyfin"))
    while True:
        m = conn.receive()
        if m.header.message_type != MessageType.method_call:
            continue
        name = m.header.fields[3]
        if name == "Get":
            r = new_method_return(m, "v", (("s", state["player"]),))
        elif name == "Pause":
            state["player"] = "Paused"
            r = new_method_return(m)
        else:
            r = new_error(m, "org.freedesktop.DBus.Error.UnknownMethod")
        conn.send(r)


# --- a fake BlueZ (org.bluez on the session bus) ------------------------------------------

ADAPTER = "/org/bluez/hci0"
bluez = {
    "adapter": {"Powered": False, "Discovering": False},
    "devices": {},
    "calls": [],
    "fail_pair": set(),
}
IN_RANGE = {   # what discovery finds
    "AA:AA:AA:AA:AA:AA": {"Name": "Xbox Wireless Controller", "Alias": "Xbox Wireless Controller",
                          "Icon": "input-gaming"},
    "BB:BB:BB:BB:BB:BB": {"Name": "JBL Speaker", "Alias": "JBL Speaker", "Icon": "audio-headset"},
    "CC:CC:CC:CC:CC:CC": {"Alias": "CC-CC-CC-CC-CC-CC"},                       # no name yet
    "DD:DD:DD:DD:DD:DD": {"Name": "Wireless Controller", "Alias": "Wireless Controller", "Class": 0x002508},
}


def _dev_path(address):
    return ADAPTER + "/dev_" + address.replace(":", "_")


def _variant(value):
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, int):
        return ("u", value)
    return ("s", value)


def _objects():
    out = {ADAPTER: {"org.bluez.Adapter1": {k: _variant(v) for k, v in bluez["adapter"].items()}}}
    for address, props in bluez["devices"].items():
        full = dict(props, Address=address)
        full.setdefault("Paired", False)
        full.setdefault("Connected", False)
        full.setdefault("Trusted", False)
        out[_dev_path(address)] = {"org.bluez.Device1": {k: _variant(v) for k, v in full.items()}}
    return out


def _device_at(path):
    for address in bluez["devices"]:
        if _dev_path(address) == path:
            return address
    return None


def fake_bluez():
    conn = open_dbus_connection(bus="SESSION")
    conn.send_and_get_reply(message_bus.RequestName("org.bluez"))
    while True:
        m = conn.receive()
        if m.header.message_type != MessageType.method_call:
            continue
        name, path, args = m.header.fields[3], m.header.fields[1], m.body
        bluez["calls"].append((name, path))
        r = None
        if name == "GetManagedObjects":
            r = new_method_return(m, "a{oa{sa{sv}}}", (_objects(),))
        elif name == "Set":
            iface, prop, (_sig, value) = args
            if iface == "org.bluez.Adapter1":
                bluez["adapter"][prop] = value
            else:
                bluez["devices"][_device_at(path)][prop] = value
            r = new_method_return(m)
        elif name == "SetDiscoveryFilter":
            r = new_method_return(m)
        elif name == "StartDiscovery":
            bluez["adapter"]["Discovering"] = True
            for address, props in IN_RANGE.items():
                bluez["devices"].setdefault(address, dict(props))
            r = new_method_return(m)
        elif name == "StopDiscovery":
            bluez["adapter"]["Discovering"] = False
            r = new_method_return(m)
        elif name == "Pair":
            address = _device_at(path)
            if address in bluez["fail_pair"]:
                r = new_error(m, "org.bluez.Error.AuthenticationFailed", "s", ("Authentication Failed",))
            else:
                bluez["devices"][address]["Paired"] = True
                r = new_method_return(m)
        elif name == "Connect":
            bluez["devices"][_device_at(path)]["Connected"] = True
            r = new_method_return(m)
        elif name == "RemoveDevice":
            bluez["devices"].pop(_device_at(args[0]), None)
            r = new_method_return(m)
        if r is None:
            r = new_error(m, "org.freedesktop.DBus.Error.UnknownMethod")
        conn.send(r)


def start():
    for f in (shell, player, fake_bluez):
        threading.Thread(target=f, daemon=True).start()
