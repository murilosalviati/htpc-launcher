"""Extensão do GNOME e player MPRIS falsos, para testar o controle.py num D-Bus de verdade."""
import json, sys, threading
from jeepney import new_method_return, new_error, MessageType
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection

estado = {
    "janelas": [
        {"appId": "htpc-launcher", "ids": ["htpc-launcher"], "title": "Launcher", "pid": 0, "minimized": False},
        {"appId": "org.jellyfin.JellyfinDesktop", "ids": ["org.jellyfin.jellyfindesktop", "jellyfin"], "title": "Jellyfin", "pid": 0, "minimized": False},
        {"appId": "rocks.shy.VacuumTube", "ids": ["rocks.shy.vacuumtube", "vacuumtube"], "title": "YouTube", "pid": 0, "minimized": False},
        {"appId": "com.moonlight_stream.Moonlight", "ids": ["com.moonlight_stream.moonlight", "moonlight"], "title": "Artemis", "pid": 0, "minimized": False},
        {"appId": "jogo", "ids": ["steam_app_1", "jogo"], "title": "Jogo teimoso", "pid": 0, "minimized": False, "teimoso": True},
    ],
    "foco": "org.jellyfin.JellyfinDesktop",
    "player": "Playing",
    "log": [],
}

def achar(app):
    a = app.lower()
    return [j for j in estado["janelas"] if a in j["ids"] or j["appId"].lower() == a]

def shell():
    conn = open_dbus_connection(bus="SESSION")
    conn.send_and_get_reply(message_bus.RequestName("org.htpc.Launcher"))
    while True:
        m = conn.receive()
        if m.header.message_type != MessageType.method_call:
            continue
        nome = m.header.fields[3]
        args = m.body
        estado["log"].append((nome, args))
        if nome == "ListWindows":
            js = [dict(j, focused=(j["appId"] == estado["foco"])) for j in estado["janelas"]]
            r = new_method_return(m, "s", (json.dumps(js),))
        elif nome == "IsRunning":
            r = new_method_return(m, "b", (bool(achar(args[0])),))
        elif nome == "Close":
            ws = achar(args[0])
            for w in ws:
                if not w.get("teimoso"):
                    estado["janelas"].remove(w)
            r = new_method_return(m, "u", (len(ws),))
        elif nome == "Activate":
            ws = achar(args[0])
            if ws: estado["foco"] = ws[0]["appId"]
            r = new_method_return(m, "b", (bool(ws),))
        elif nome == "ShowLauncher":
            estado["foco"] = "htpc-launcher"
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
        nome = m.header.fields[3]
        if nome == "Get":
            r = new_method_return(m, "v", (("s", estado["player"]),))
        elif nome == "Pause":
            estado["player"] = "Paused"
            r = new_method_return(m)
        else:
            r = new_error(m, "org.freedesktop.DBus.Error.UnknownMethod")
        conn.send(r)

def iniciar():
    for f in (shell, player):
        threading.Thread(target=f, daemon=True).start()
