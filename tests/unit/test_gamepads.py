import struct
from types import SimpleNamespace

import pytest

from htpc.backends.linux.gamepads import DirWatch, EvdevGamepads


def inotify_event(mask, name=b""):
    """One struct inotify_event; the kernel pads the name with NULs to 16 bytes."""
    padded = name + b"\0" * (16 - len(name) % 16) if name else b""
    return struct.pack("iIII", 1, mask, 0, len(padded)) + padded


def test_inotify_events_give_the_names_that_changed():
    data = inotify_event(DirWatch.IN_CREATE, b"event7") + inotify_event(DirWatch.IN_ATTRIB, b"event7") \
        + inotify_event(DirWatch.IN_DELETE, b"js0")
    assert DirWatch.parse(data) == ({"event7", "js0"}, False)


def test_an_inotify_overflow_is_reported():
    assert DirWatch.parse(inotify_event(DirWatch.IN_Q_OVERFLOW))[1] is True


def test_a_changed_entry_is_tried_again_even_if_it_could_not_be_opened_before():
    pads = EvdevGamepads()
    pads.ignored = {"/dev/input/event7", "/dev/input/event3"}
    pads._rescan = lambda events: None
    pads._input_changed({"event7"}, [])
    assert pads.ignored == {"/dev/input/event3"}
    pads._input_changed(None, [])   # overflow: try everything again
    assert pads.ignored == set()


@pytest.fixture
def ecodes():
    return pytest.importorskip("evdev").ecodes


def raw(type_, code, value):
    return SimpleNamespace(type=type_, code=code, value=value)


def test_a_stick_only_reports_crossing_the_dead_zone_and_reads_its_range_once(ecodes):
    pads = EvdevGamepads()
    ranges_read = []
    dev = SimpleNamespace(absinfo=lambda code: ranges_read.append(code) or SimpleNamespace(min=-32768, max=32767))
    values = (0, 5000, 20000, 30000, 32767, 31000, 1000, -30000, -32000, 0)
    events = [e for v in values for e in pads.translate("p", dev, raw(ecodes.EV_ABS, ecodes.ABS_X, v))]
    assert [round(e.value, 2) for e in events] == [0.61, 0.03, -0.92, 0.0]
    assert ranges_read == [ecodes.ABS_X]


def test_the_dpad_hat_becomes_presses_and_releases(ecodes):
    pads = EvdevGamepads()
    events = pads.translate("p", None, raw(ecodes.EV_ABS, ecodes.ABS_HAT0X, 1)) \
        + pads.translate("p", None, raw(ecodes.EV_ABS, ecodes.ABS_HAT0X, -1))
    assert [(e.name, e.value) for e in events] == [("right", 1), ("right", 0), ("left", 1)]


def test_flush_drops_what_is_waiting_and_centers_the_sticks(ecodes):
    class Pending:
        def __init__(self, n):
            self.n = n

        def read_one(self):
            if self.n:
                self.n -= 1
                return object()
            return None

    pads = EvdevGamepads()
    waiting = Pending(5)
    pads.devs = {"p": waiting}
    pads.sticks[("p", ecodes.ABS_X)] = 1
    pads.flush()
    assert waiting.n == 0 and pads.sticks == {}


def test_bluetooth_le_gamepads_are_not_virtual(tmp_path):
    from htpc.backends.linux.gamepads import is_virtual
    sys_input = tmp_path / "class/input"
    sys_input.mkdir(parents=True)
    devices = {
        # Steam Input's pad, made with uinput
        "event20": tmp_path / "devices/virtual/input/input40",
        # an Xbox controller over Bluetooth LE: HID through uhid
        "event21": tmp_path / "devices/virtual/misc/uhid/0005:045E:0B13.0003/input/input41",
        # a USB gamepad
        "event22": tmp_path / "devices/pci0000:00/0000:00:14.0/usb1/1-2/input/input42",
    }
    for event, target in devices.items():
        target.mkdir(parents=True)
        (sys_input / event).mkdir()
        (sys_input / event / "device").symlink_to(target)
    assert is_virtual("/dev/input/event20", str(sys_input))
    assert not is_virtual("/dev/input/event21", str(sys_input))
    assert not is_virtual("/dev/input/event22", str(sys_input))
