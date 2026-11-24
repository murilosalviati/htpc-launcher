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


def start():
    for f in (shell, player):
        threading.Thread(target=f, daemon=True).start()
