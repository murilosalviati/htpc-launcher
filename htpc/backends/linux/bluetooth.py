# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Bluetooth through BlueZ, on the system D-Bus (jeepney, no extra packages).

Pairing a gamepad: power the adapter on, search (discovery stays on while the
D-Bus connection that started it is open), then Pair → Trusted → Connect.
Gamepads use "Just Works" pairing. In a GNOME session, GNOME's own Bluetooth
agent is BlueZ's default: it asks for a confirmation in a window the full-screen
launcher hides, nobody answers, and the gamepad's pairing fails
(AuthenticationFailed). So while pairing, the launcher registers its own agent
(PairingAgent, NoInputNoOutput, accepting) as the default one, and tries once
more when the first attempt is refused.
"""

import logging
import os
import threading
import time

from jeepney import HeaderFields, MessageType, new_error, new_method_call, new_method_return
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import unwrap_msg

from ..base import BluetoothDevice, Bluetooth
from .dbus import DBusAddress, DBusClient

log = logging.getLogger("htpc")

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PAIR_TIMEOUT = 40
CALL_TIMEOUT = 8
RETRY_AFTER = 2.0     # seconds before the second Pair, when the first was refused
RETRY_ERRORS = ("AuthenticationFailed", "AuthenticationCanceled", "AuthenticationRejected",
                "ConnectionAttemptFailed")
AGENT_PATH = "/org/htpc/launcher/agent"

# What the pairing agent answers BlueZ: accept everything, like a device without
# a screen or keyboard would. (member -> (signature, body))
AGENT_REPLIES = {
    "RequestPinCode": ("s", ("0000",)),
    "RequestPasskey": ("u", (0,)),
    "RequestConfirmation": (None, ()),
    "RequestAuthorization": (None, ()),
    "AuthorizeService": (None, ()),
    "DisplayPinCode": (None, ()),
    "DisplayPasskey": (None, ()),
    "Release": (None, ()),
    "Cancel": (None, ()),
}


class PairingAgent:
    """A BlueZ agent of our own, the default one while it lives (its own system
    bus connection, served by a thread; closing it gives the role back)."""

    def __init__(self, bus="SYSTEM", connect=open_dbus_connection):
        self.conn = connect(bus=bus)
        self.stopped = threading.Event()
        manager = DBusAddress("/org/bluez", bus_name=BLUEZ, interface="org.bluez.AgentManager1")
        unwrap_msg(self.conn.send_and_get_reply(
            new_method_call(manager, "RegisterAgent", "os", (AGENT_PATH, "NoInputNoOutput")), timeout=CALL_TIMEOUT))
        unwrap_msg(self.conn.send_and_get_reply(
            new_method_call(manager, "RequestDefaultAgent", "o", (AGENT_PATH,)), timeout=CALL_TIMEOUT))
        self.thread = threading.Thread(target=self._serve, daemon=True, name="bluetooth-agent")
        self.thread.start()

    def _serve(self):
        while not self.stopped.is_set():
            try:
                msg = self.conn.receive(timeout=0.5)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001 - connection closed
                return
            reply = agent_reply(msg)
            if reply is not None:
                try:
                    self.conn.send(reply)
                except Exception:  # noqa: BLE001
                    return

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
        try:
            self.conn.close()   # BlueZ forgets the agent with its connection
        except Exception:  # noqa: BLE001
            pass


def agent_reply(msg):
    """The answer to a call BlueZ makes on our agent, or None for anything else."""
    if msg.header.message_type != MessageType.method_call:
        return None
    if msg.header.fields.get(HeaderFields.path) != AGENT_PATH:
        return None
    member = msg.header.fields.get(HeaderFields.member)
    if member not in AGENT_REPLIES:
        return new_error(msg, "org.bluez.Error.Rejected")
    log.info("bluetooth agent: %s", member)
    signature, body = AGENT_REPLIES[member]
    return new_method_return(msg, signature, body)

# Names of gamepads that don't announce themselves as one (Icon/Class missing).
GAMEPAD_WORDS = ("controller", "gamepad", "joy-con", "xbox", "dualsense", "dualshock", "8bitdo",
                 "pro controller", "wireless controller", "joystick")


def is_gamepad(props):
    """From a Device1's properties: does it look like a gamepad?"""
    if props.get("Icon") == "input-gaming":
        return True
    cls = props.get("Class") or 0
    # Major class 0x05 (peripheral), minor joystick (0x04) or gamepad (0x08)
    if (cls & 0x1F00) == 0x0500 and (cls & 0x0C) in (0x04, 0x08):
        return True
    name = (props.get("Name") or props.get("Alias") or "").lower()
    return any(w in name for w in GAMEPAD_WORDS)


AUDIO_WORDS = ("headphone", "headset", "earbud", "buds", "speaker", "soundbar", "sound bar", "jbl",
               "airpods", "bose", "sony wh", "sony wf", "boombox", "flip", "charge")


def is_audio(props):
    """From a Device1's properties: headphones, a speaker...?"""
    if str(props.get("Icon") or "").startswith("audio-"):
        return True
    cls = props.get("Class") or 0
    if (cls & 0x1F00) == 0x0400:      # major class: audio/video
        return True
    name = (props.get("Name") or props.get("Alias") or "").lower()
    return any(w in name for w in AUDIO_WORDS)


def device_kind(props):
    """"gamepad", "keyboard", "mouse", "audio", or "" for anything else."""
    if is_gamepad(props):
        return "gamepad"
    icon = str(props.get("Icon") or "")
    cls = props.get("Class") or 0
    peripheral = (cls & 0x1F00) == 0x0500
    if icon == "input-keyboard" or (peripheral and cls & 0x40):
        return "keyboard"
    if icon in ("input-mouse", "input-tablet") or (peripheral and cls & 0x80):
        return "mouse"
    name = (props.get("Name") or props.get("Alias") or "").lower()
    if "keyboard" in name or "teclado" in name:
        return "keyboard"
    if any(w in name for w in ("mouse", "trackpad", "touchpad")):
        return "mouse"
    if is_audio(props):
        return "audio"
    return ""


def _plain(props):
    """D-Bus variants (signature, value) → plain values."""
    return {k: (v[1] if isinstance(v, tuple) and len(v) == 2 else v) for k, v in props.items()}


class BluezBluetooth(Bluetooth):
    def __init__(self, bus="SYSTEM", sysfs="/sys/class/bluetooth"):
        # Adapters the kernel knows about. Checked first: without one, BlueZ is not
        # running and asking it over D-Bus waits for it to start (and time out).
        self.sysfs = sysfs
        # Discovery stays on while this connection is open; close() ends it.
        self.dbus = DBusClient(bus)

    # --- D-Bus plumbing -----------------------------------------------------------------

    def _call(self, path, interface, method, signature=None, body=(), timeout=CALL_TIMEOUT):
        return self.dbus.call(DBusAddress(path, bus_name=BLUEZ, interface=interface),
                              method, signature, body, timeout)

    def _set(self, path, interface, name, signature, value):
        self._call(path, "org.freedesktop.DBus.Properties", "Set", "ssv",
                   (interface, name, (signature, value)))

    def _objects(self):
        return self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]

    def close(self):
        self.dbus.reset()

    # --- Bluetooth ----------------------------------------------------------------------

    def _adapter(self, objects=None):
        """(path, properties) of the first adapter, or (None, None)."""
        objects = objects if objects is not None else self._objects()
        for path in sorted(objects):
            if ADAPTER in objects[path]:
                return path, _plain(objects[path][ADAPTER])
        return None, None

    def available(self):
        if self.sysfs is not None:
            try:
                if not any(name.startswith("hci") for name in os.listdir(self.sysfs)):
                    return False
            except OSError:
                return False
        try:
            return self._adapter()[0] is not None
        except Exception as e:  # noqa: BLE001 - no BlueZ, no system bus
            log.debug("bluetooth: %s", e)
            self.close()
            return False

    def start_search(self):
        path, props = self._adapter()
        if path is None:
            raise RuntimeError("no Bluetooth adapter")
        if not props.get("Powered"):
            self._set(path, ADAPTER, "Powered", "b", True)
        try:
            self._call(path, ADAPTER, "SetDiscoveryFilter", "a{sv}", ({"Transport": ("s", "auto")},))
        except Exception as e:  # noqa: BLE001 - older BlueZ: search without the filter
            log.debug("bluetooth: no discovery filter: %s", e)
        if not props.get("Discovering"):
            self._call(path, ADAPTER, "StartDiscovery")

    def stop_search(self):
        try:
            path, props = self._adapter()
            if path is not None and props.get("Discovering"):
                self._call(path, ADAPTER, "StopDiscovery")
        except Exception as e:  # noqa: BLE001 - it stops anyway when the connection closes
            log.debug("bluetooth: stop discovery: %s", e)
        self.close()

    def devices(self):
        objects = self._objects()
        adapter, _ = self._adapter(objects)
        found = []
        for path, interfaces in objects.items():
            if DEVICE not in interfaces or (adapter and not path.startswith(adapter + "/")):
                continue
            p = _plain(interfaces[DEVICE])
            found.append(BluetoothDevice(
                address=p.get("Address", ""), name=p.get("Alias") or p.get("Name") or p.get("Address", ""),
                paired=bool(p.get("Paired")), connected=bool(p.get("Connected")),
                gamepad=is_gamepad(p), audio=device_kind(p) == "audio", kind=device_kind(p), path=path,
                has_name=bool(p.get("Name"))))
        found.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
        return found

    def _path(self, address):
        for d in self.devices():
            if d.address == address:
                return d.path
        raise RuntimeError(f"{address} is not in range any more")

    def pair(self, address, agent=PairingAgent, sleep=time.sleep):
        path = self._path(address)
        props = _plain(self._objects()[path][DEVICE])
        if not props.get("Paired"):
            helper = None
            try:
                helper = agent(self.dbus.bus)
            except Exception as e:  # noqa: BLE001 - pair with whatever agent there is
                log.warning("bluetooth: no pairing agent of our own: %s", e)
            try:
                try:
                    self._call(path, DEVICE, "Pair", timeout=PAIR_TIMEOUT)
                except Exception as e:  # noqa: BLE001
                    if not any(name in str(e) for name in RETRY_ERRORS):
                        raise
                    log.info("bluetooth: pairing %s refused (%s), trying again", address, e)
                    sleep(RETRY_AFTER)
                    self._call(path, DEVICE, "Pair", timeout=PAIR_TIMEOUT)
            finally:
                if helper is not None:
                    helper.close()
        self._set(path, DEVICE, "Trusted", "b", True)   # reconnects by itself from now on
        if not props.get("Connected"):
            self._call(path, DEVICE, "Connect", timeout=PAIR_TIMEOUT)
        log.info("bluetooth: paired %s", address)

    def forget(self, address):
        path = self._path(address)
        adapter = path.rsplit("/", 1)[0]
        self._call(adapter, ADAPTER, "RemoveDevice", "o", (path,))
        log.info("bluetooth: removed %s", address)
