# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Bluetooth through BlueZ, on the system D-Bus (jeepney, no extra packages).

Pairing a gamepad: power the adapter on, search (discovery stays on while the
D-Bus connection that started it is open), then Pair → Trusted → Connect.
Gamepads use "Just Works" pairing: with no agent registered by us, BlueZ pairs
with the NoInputNoOutput capability, which is what they expect.
"""

import logging
import os
import threading

from ..base import BluetoothDevice, Bluetooth

log = logging.getLogger("htpc")

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
PAIR_TIMEOUT = 40
CALL_TIMEOUT = 8

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


def _plain(props):
    """D-Bus variants (signature, value) → plain values."""
    return {k: (v[1] if isinstance(v, tuple) and len(v) == 2 else v) for k, v in props.items()}


class BluezBluetooth(Bluetooth):
    def __init__(self, bus="SYSTEM", sysfs="/sys/class/bluetooth"):
        self.bus = bus
        # Adapters the kernel knows about. Checked first: without one, BlueZ is not
        # running and asking it over D-Bus waits for it to start (and time out).
        self.sysfs = sysfs
        self._conn = None
        self._lock = threading.RLock()

    # --- D-Bus plumbing -----------------------------------------------------------------

    def _connection(self):
        from jeepney.io.blocking import open_dbus_connection
        if self._conn is None:
            self._conn = open_dbus_connection(bus=self.bus)
        return self._conn

    def _call(self, path, interface, method, signature=None, body=(), timeout=CALL_TIMEOUT):
        from jeepney import DBusAddress, new_method_call
        from jeepney.wrappers import unwrap_msg
        with self._lock:
            try:
                msg = new_method_call(DBusAddress(path, bus_name=BLUEZ, interface=interface),
                                      method, signature, body)
                return unwrap_msg(self._connection().send_and_get_reply(msg, timeout=timeout))
            except (ConnectionError, OSError):
                self.close()
                raise

    def _set(self, path, interface, name, signature, value):
        self._call(path, "org.freedesktop.DBus.Properties", "Set", "ssv",
                   (interface, name, (signature, value)))

    def _objects(self):
        return self._call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
            self._conn = None

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
                gamepad=is_gamepad(p), path=path, has_name=bool(p.get("Name"))))
        found.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
        return found

    def _path(self, address):
        for d in self.devices():
            if d.address == address:
                return d.path
        raise RuntimeError(f"{address} is not in range any more")

    def pair(self, address):
        path = self._path(address)
        props = _plain(self._objects()[path][DEVICE])
        if not props.get("Paired"):
            self._call(path, DEVICE, "Pair", timeout=PAIR_TIMEOUT)
        self._set(path, DEVICE, "Trusted", "b", True)   # reconnects by itself from now on
        if not props.get("Connected"):
            self._call(path, DEVICE, "Connect", timeout=PAIR_TIMEOUT)
        log.info("bluetooth: paired %s", address)

    def forget(self, address):
        path = self._path(address)
        adapter = path.rsplit("/", 1)[0]
        self._call(adapter, ADAPTER, "RemoveDevice", "o", (path,))
        log.info("bluetooth: removed %s", address)
