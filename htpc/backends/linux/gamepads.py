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
    # Raw button code -> normalized name, by position as the kernel documents it
    # (BTN_WEST is the left face button, BTN_NORTH the top one). Sony and Nintendo
    # drivers follow this; Xbox-style drivers do not, see uses_xbox_codes().
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


# Xbox-style drivers send the X button (left) as BTN_X and Y (top) as BTN_Y. In
# the kernel BTN_X is the same code as BTN_NORTH and BTN_Y as BTN_WEST, so by
# position they come out swapped: Y read as X. (SDL's mappings for these pads
# account for it too.)
XBOX_DRIVERS = ("xpad", "xone", "xpadneo", "microsoft")


def uses_xbox_codes(path, name=""):
    """True when the gamepad sends X/Y the Xbox way (swapped by position): its
    driver is an Xbox one (xpad on USB or a dongle, xone, xpadneo, hid-microsoft),
    or its name says Xbox (Bluetooth Xbox pads on hid-generic number their buttons
    the same way, and so do Steam Input's virtual "X-Box 360" pads)."""
    lowered = (name or "").lower()
    if "xbox" in lowered or "x-box" in lowered:
        return True
    node = os.path.realpath(f"/sys/class/input/{os.path.basename(path)}/device")
    # The driver sits a few levels up: on the USB interface or the HID device.
    for _ in range(4):
        link = os.path.join(node, "driver")
        if os.path.exists(link):
            driver = os.path.basename(os.path.realpath(link)).lower()
            return any(d in driver for d in XBOX_DRIVERS)
        node = os.path.dirname(node)
    return False


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
        self.xbox_codes = {} # path -> X/Y come swapped (Xbox-style driver)

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
                self.xbox_codes[path] = uses_xbox_codes(path, dev.name)
                log.info("gamepad connected: %s (%s)%s%s", dev.name, path,
                         " [virtual]" if self.virtual[path] else "",
                         " [Xbox X/Y codes]" if self.xbox_codes[path] else "")
            else:
                dev.close()
                self.ignored.add(path)

    def _remove(self, path, events):
        dev = self.devs.pop(path, None)
        self.virtual.pop(path, None)
        self.sysfs.pop(path, None)
        self.xbox_codes.pop(path, None)
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
            name = BUTTONS[ev.code]
            if name in ("x", "y") and self.xbox_codes.get(path):
                name = "y" if name == "x" else "x"
            return [GamepadEvent(path, "button", name, ev.value)]
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
