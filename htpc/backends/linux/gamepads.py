# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""Reading gamepads on Linux with evdev, as normalized GamepadEvents.

The devices are read without grabbing them, so the apps still get every button.
A logged-in user can read gamepads without extra groups (udev's uaccess rule).
"""

import ctypes
import logging
import os
import select
import struct
import time

from ..base import STICK_DEAD_ZONE, Battery, GamepadEvent, Gamepads

try:
    import evdev
    from evdev import ecodes
except ImportError:  # the launcher still works with a keyboard
    evdev = None

log = logging.getLogger("htpc")

RESCAN_INTERVAL = 2.0   # without inotify: how often to look for new gamepads
INPUT_DIR = "/dev/input"
POWER_SUPPLY = "/sys/class/power_supply"
LEVELS = {"full": "full", "high": "high", "normal": "normal", "low": "low", "critical": "critical"}


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


class DirWatch:
    """inotify on a folder: the entries that were created, removed or had their
    permissions changed. Raises OSError where inotify can't be used."""

    IN_ATTRIB, IN_CREATE, IN_DELETE, IN_Q_OVERFLOW = 0x4, 0x100, 0x200, 0x4000
    IN_NONBLOCK, IN_CLOEXEC = 0o4000, 0o2000000
    EVENT = struct.Struct("iIII")   # struct inotify_event, then `len` bytes of name

    def __init__(self, path):
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.inotify_init1(self.IN_NONBLOCK | self.IN_CLOEXEC)
        if fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        if libc.inotify_add_watch(fd, os.fsencode(path), self.IN_ATTRIB | self.IN_CREATE | self.IN_DELETE) < 0:
            error = ctypes.get_errno()
            os.close(fd)
            raise OSError(error, f"can't watch {path}")
        self.fd = fd

    def changes(self):
        """The names that changed since the last call, or None if the kernel had to
        drop some (then anything may have changed)."""
        names, overflow = set(), False
        while True:
            try:
                data = os.read(self.fd, 64 * 1024)
            except BlockingIOError:
                break
            if not data:
                break
            found, dropped = self.parse(data)
            names |= found
            overflow |= dropped
        return None if overflow else names

    @classmethod
    def parse(cls, data):
        """(set of names, overflowed) from a buffer of inotify events."""
        names, overflow, offset = set(), False, 0
        while offset + cls.EVENT.size <= len(data):
            _wd, mask, _cookie, length = cls.EVENT.unpack_from(data, offset)
            start = offset + cls.EVENT.size
            name = data[start:start + length].split(b"\0", 1)[0]
            offset = start + length
            if mask & cls.IN_Q_OVERFLOW:
                overflow = True
            elif name:
                names.add(os.fsdecode(name))
        return names, overflow


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
        self.sticks = {}     # (path, stick axis) -> -1 / 0 / 1: which side of the dead zone
        self.ranges = {}     # (path, stick axis) -> (middle, half): absinfo never changes
        self.next_scan = 0.0     # without inotify: when to look for new gamepads again
        self.watch = None        # DirWatch on /dev/input; False when it can't be used
        self.rescan_due = True   # with the watch: look once at start, then on changes
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
            if is_gamepad(dev) and is_virtual(path):
                # Steam Input's copy of a real pad: its events would double every
                # press, and reading them would wake us for every mirrored stick move.
                # Not opened at all (it stays in `ignored` while it exists).
                log.info("virtual gamepad left alone: %s (%s)", dev.name, path)
                dev.close()
                self.ignored.add(path)
            elif is_gamepad(dev):
                self.devs[path] = dev
                self.virtual[path] = False
                self.sysfs[path] = os.path.realpath(f"/sys/class/input/{os.path.basename(path)}/device")
                self.xbox_codes[path] = uses_xbox_codes(path, dev.name)
                log.info("gamepad connected: %s (%s)%s", dev.name, path,
                         " [Xbox X/Y codes]" if self.xbox_codes[path] else "")
            else:
                dev.close()
                self.ignored.add(path)

    def _remove(self, path, events):
        dev = self.devs.pop(path, None)
        self.virtual.pop(path, None)
        self.sysfs.pop(path, None)
        self.xbox_codes.pop(path, None)
        for table in (self.hats, self.sticks, self.ranges):
            for key in [k for k in table if k[0] == path]:
                del table[key]
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
            key = (path, ev.code)
            if key not in self.ranges:
                info = dev.absinfo(ev.code)   # an ioctl: once per stick, not per event
                self.ranges[key] = ((info.max + info.min) / 2, (info.max - info.min) / 2 or 1)
            middle, half = self.ranges[key]
            value = max(-1.0, min(1.0, (ev.value - middle) / half))
            side = 1 if value > STICK_DEAD_ZONE else -1 if value < -STICK_DEAD_ZONE else 0
            if side == self.sticks.get(key, 0):
                return []   # still on the same side of the dead zone: nothing new
            self.sticks[key] = side
            return [GamepadEvent(path, "axis", STICK[ev.code], value)]
        return []

    def flush(self):
        """Read and drop whatever is waiting on every gamepad."""
        if evdev is None:
            return
        events = []
        for path, dev in list(self.devs.items()):
            try:
                for _ in range(100_000):   # a bound, in case events keep arriving as fast as we read
                    if dev.read_one() is None:
                        break
            except BlockingIOError:
                pass
            except OSError:
                self._remove(path, events)
        # The dropped events may have moved the d-pad or a stick: start again from the middle.
        self.hats.clear()
        self.sticks.clear()

    # --- hotplug: inotify on /dev/input, or a look every RESCAN_INTERVAL without it ------

    def _hotplug(self):
        """The DirWatch on /dev/input, or None when inotify can't be used here."""
        if self.watch is None:
            try:
                self.watch = DirWatch(INPUT_DIR)
            except (OSError, AttributeError) as e:   # no inotify, no /dev/input...
                log.info("can't watch %s (%s): looking for gamepads every %.0f s",
                         INPUT_DIR, e, RESCAN_INTERVAL)
                self.watch = False
        return self.watch or None

    def _input_changed(self, names, events):
        """Entries of /dev/input appeared, went or changed permissions. One we could
        not open may be readable now: udev grants access a moment after a gamepad
        appears, so the first try can fail."""
        if names is None:
            self.ignored.clear()   # the kernel dropped events: anything may have changed
        else:
            self.ignored -= {f"{INPUT_DIR}/{n}" for n in names}   # as evdev.list_devices() names them
        self._rescan(events)

    def fds(self):
        """File descriptors a main loop can wait on (when one is readable, call
        poll(0)): the gamepads and the /dev/input watch. None without inotify: then
        poll() must be called regularly to notice new gamepads."""
        if evdev is None or self._hotplug() is None:
            return None
        return [self.watch.fd, *(dev.fd for dev in self.devs.values())]

    def poll(self, timeout):
        if evdev is None:
            time.sleep(timeout)
            return []
        events = []
        watch = self._hotplug()
        if watch is not None:
            if self.rescan_due:   # the first look; after that, only when /dev/input changes
                self.rescan_due = False
                self._rescan(events)
        else:
            if time.monotonic() >= self.next_scan:
                self._rescan(events)
                self.next_scan = time.monotonic() + RESCAN_INTERVAL
            timeout = min(timeout, max(0.0, self.next_scan - time.monotonic()))
        by_fd = {dev.fd: path for path, dev in self.devs.items()}
        waiting = list(by_fd) + ([watch.fd] if watch is not None else [])
        if not waiting:
            time.sleep(timeout)
            return events
        try:
            ready, _, _ = select.select(waiting, [], [], timeout)
        except (OSError, ValueError):
            ready = list(by_fd)  # a closed fd: reading it will remove the device
        for fd in ready:
            if watch is not None and fd == watch.fd:
                self._input_changed(watch.changes(), events)
                continue
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
