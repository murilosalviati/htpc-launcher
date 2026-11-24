# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Reading gamepads on Linux with evdev, as normalized GamepadEvents.

The devices are read without grabbing them, so the apps still get every button.
A logged-in user can read gamepads without extra groups (udev's uaccess rule).
"""

import logging
import os
import select
import time

from ..base import Battery, GamepadEvent, Gamepads

try:
    import evdev
    from evdev import ecodes
except ImportError:  # the launcher still works with a keyboard
    evdev = None

log = logging.getLogger("htpc")

RESCAN_INTERVAL = 2.0
POWER_SUPPLY = "/sys/class/power_supply"
LEVELS = {"full": "full", "high": "high", "normal": "normal", "low": "low", "critical": "critical"}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def device_batteries(root=POWER_SUPPLY):
    """(device sysfs path, Battery without a name) for every battery that belongs
    to a device (scope "Device": gamepads, mice...), not to the machine."""
    out = []
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        d = os.path.join(root, name)
        if _read(f"{d}/type") != "Battery" or _read(f"{d}/scope") != "Device":
            continue
        capacity = _read(f"{d}/capacity")
        level = _read(f"{d}/capacity_level").lower()
        status = _read(f"{d}/status").lower()
        battery = Battery(name="", percent=int(capacity) if capacity.isdigit() else None,
                          level=LEVELS.get(level, ""), charging=status == "charging")
        out.append((os.path.realpath(f"{d}/device"), battery))
    return out

if evdev is not None:
    # Raw button code -> normalized name. BTN_WEST/BTN_NORTH follow what the
    # previous versions did (X and Y on an Xbox layout).
    BUTTONS = {
        ecodes.BTN_SOUTH: "a", ecodes.BTN_EAST: "b",
        ecodes.BTN_WEST: "x", ecodes.BTN_NORTH: "y",
        ecodes.BTN_START: "start", ecodes.BTN_SELECT: "select",
        ecodes.BTN_TL: "l1", ecodes.BTN_TR: "r1", ecodes.BTN_MODE: "guide",
        ecodes.BTN_DPAD_UP: "up", ecodes.BTN_DPAD_DOWN: "down",
        ecodes.BTN_DPAD_LEFT: "left", ecodes.BTN_DPAD_RIGHT: "right",
    }
    STICK = {ecodes.ABS_X: "lx", ecodes.ABS_Y: "ly"}
    HATS = {ecodes.ABS_HAT0X: ("left", "right"), ecodes.ABS_HAT0Y: ("up", "down")}


def is_gamepad(dev):
    keys = dev.capabilities().get(ecodes.EV_KEY, [])
    return ecodes.BTN_SOUTH in keys and ecodes.BTN_START in keys


def is_virtual(path):
    """True for gamepads made by software (uinput), e.g. Steam Input's virtual pads."""
    name = os.path.basename(path)  # eventN
    real = os.path.realpath(f"/sys/class/input/{name}/device")
    return "/devices/virtual/" in real


class EvdevGamepads(Gamepads):
    def __init__(self):
        self.devs = {}       # path -> InputDevice
        self.ignored = set()
        self.hats = {}       # (path, hat axis) -> -1 / 0 / 1
        self.next_scan = 0.0
        self.virtual = {}    # path -> made by software (not counted in connected())
        self.sysfs = {}      # path -> the input device's real sysfs path

    def available(self):
        return evdev is not None

    def connected(self):
        seen, names = set(), []
        for path, dev in sorted(self.devs.items()):
            if self.virtual.get(path):
                continue
            # A gamepad that shows up as more than one device still counts once.
            key = getattr(dev, "uniq", "") or path
            if key in seen:
                continue
            seen.add(key)
            names.append(dev.name)
        return names

    def batteries(self, root=POWER_SUPPLY):
        """A power supply belongs to a gamepad when its device is the gamepad's input
        device or one of its parents (e.g. the HID device of a Bluetooth pad)."""
        supplies = device_batteries(root)
        if not supplies:
            return []
        out, seen = [], set()
        for path, dev in sorted(self.devs.items()):
            if self.virtual.get(path):
                continue
            sysfs = self.sysfs.get(path) or os.path.realpath(
                f"/sys/class/input/{os.path.basename(path)}/device")
            for owner, battery in supplies:
                if owner not in seen and (sysfs == owner or sysfs.startswith(owner + "/")):
                    seen.add(owner)
                    battery.name = dev.name
                    out.append(battery)
                    break
        return out

    def _rescan(self, events):
        paths = set(evdev.list_devices())
        self.ignored &= paths  # a device that disappeared may come back as something else
        for path in paths - self.devs.keys() - self.ignored:
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                self.ignored.add(path)  # no permission: keyboards, mice...
                continue
            if is_gamepad(dev):
                self.devs[path] = dev
                self.virtual[path] = is_virtual(path)
                self.sysfs[path] = os.path.realpath(f"/sys/class/input/{os.path.basename(path)}/device")
                log.info("gamepad connected: %s (%s)%s", dev.name, path,
                         " [virtual]" if self.virtual[path] else "")
            else:
                dev.close()
                self.ignored.add(path)

    def _remove(self, path, events):
        dev = self.devs.pop(path, None)
        self.virtual.pop(path, None)
        self.sysfs.pop(path, None)
        for key in [k for k in self.hats if k[0] == path]:
            del self.hats[key]
        if dev:
            log.info("gamepad disconnected: %s", dev.name)
            try:
                dev.close()
            except OSError:
                pass
        events.append(GamepadEvent(path, "disconnected", "", 0))

    def translate(self, path, dev, ev):
        """Raw evdev event -> list of GamepadEvent (empty for events we do not use)."""
        if ev.type == ecodes.EV_KEY and ev.value in (0, 1) and ev.code in BUTTONS:
            return [GamepadEvent(path, "button", BUTTONS[ev.code], ev.value)]
        if ev.type != ecodes.EV_ABS:
            return []
        if ev.code in HATS:
            # The d-pad as a hat axis: turn it into up/down/left/right presses and releases.
            neg, pos = HATS[ev.code]
            value = max(-1, min(1, ev.value))
            before = self.hats.get((path, ev.code), 0)
            if value == before:
                return []
            self.hats[(path, ev.code)] = value
            out = []
            if before:
                out.append(GamepadEvent(path, "button", neg if before < 0 else pos, 0))
            if value:
                out.append(GamepadEvent(path, "button", neg if value < 0 else pos, 1))
            return out
        if ev.code in STICK:
            info = dev.absinfo(ev.code)
            middle = (info.max + info.min) / 2
            half = (info.max - info.min) / 2 or 1
            value = max(-1.0, min(1.0, (ev.value - middle) / half))
            return [GamepadEvent(path, "axis", STICK[ev.code], value)]
        return []

    def poll(self, timeout):
        if evdev is None:
            time.sleep(timeout)
            return []
        events = []
        if time.monotonic() >= self.next_scan:
            self._rescan(events)
            self.next_scan = time.monotonic() + RESCAN_INTERVAL
        if not self.devs:
            time.sleep(min(timeout, max(0.0, self.next_scan - time.monotonic())))
            return events
        by_fd = {dev.fd: path for path, dev in self.devs.items()}
        try:
            ready, _, _ = select.select(list(by_fd), [], [], timeout)
        except (OSError, ValueError):
            ready = list(by_fd)  # a closed fd: reading it will remove the device
        for fd in ready:
            path = by_fd[fd]
            dev = self.devs.get(path)
            try:
                for ev in dev.read():
                    events.extend(self.translate(path, dev, ev))
            except BlockingIOError:
                pass
            except OSError:
                self._remove(path, events)
        return events
