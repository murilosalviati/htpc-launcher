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


def test_bluetooth_le_battery_comes_from_bluez():
    from types import SimpleNamespace
    from htpc.backends.linux.gamepads import EvdevGamepads
    pads = EvdevGamepads.__new__(EvdevGamepads)
    pads.devs = {"/dev/input/event21": SimpleNamespace(name="Xbox Wireless Controller", uniq="aa:bb:cc:dd:ee:ff",
                                                       info=SimpleNamespace(vendor=0x045E))}
    pads.virtual, pads.sysfs = {}, {"/dev/input/event21": "/nowhere"}
    asked = []
    pads.bluez_lookup = lambda: asked.append(1) or {"AA:BB:CC:DD:EE:FF": 64}
    status = pads.pads(root="/nonexistent")
    assert [(p.kind, p.battery.percent) for p in status] == [("xbox", 64)]
    pads.pads(root="/nonexistent")
    assert len(asked) == 1   # asked again only after BLUEZ_EVERY


def test_bluez_batteries_reads_battery1():
    from htpc.backends.linux.gamepads import bluez_batteries

    class Client:
        def call(self, address, method, timeout=2):
            return ({
                "/org/bluez/hci0/dev_AA": {"org.bluez.Device1": {"Address": ("s", "aa:bb:cc:dd:ee:ff")},
                                           "org.bluez.Battery1": {"Percentage": ("y", 64)}},
                "/org/bluez/hci0/dev_BB": {"org.bluez.Device1": {"Address": ("s", "11:22:33:44:55:66")}},
            },)
    assert bluez_batteries(Client()) == {"AA:BB:CC:DD:EE:FF": 64}


def test_which_axes_are_triggers(ecodes):
    from htpc.backends.linux.gamepads import trigger_axes
    keys = [ecodes.BTN_SOUTH, ecodes.BTN_START]
    ps = {ecodes.EV_KEY: keys + [ecodes.BTN_TL2, ecodes.BTN_TR2], ecodes.EV_ABS: [ecodes.ABS_Z, ecodes.ABS_RZ]}
    xbox_bt = {ecodes.EV_KEY: keys, ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_BRAKE, ecodes.ABS_GAS]}
    xbox_usb = {ecodes.EV_KEY: keys, ecodes.EV_ABS: [ecodes.ABS_Z, ecodes.ABS_RZ, ecodes.ABS_RX, ecodes.ABS_RY]}
    dinput = {ecodes.EV_KEY: keys, ecodes.EV_ABS: [ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_Z, ecodes.ABS_RZ]}
    assert trigger_axes(ps) == {}   # sends BTN_TL2 / BTN_TR2 already
    assert trigger_axes(xbox_bt) == {ecodes.ABS_BRAKE: "l2", ecodes.ABS_GAS: "r2"}
    assert trigger_axes(xbox_usb) == {ecodes.ABS_Z: "l2", ecodes.ABS_RZ: "r2"}
    assert trigger_axes(dinput) == {}   # Z / RZ are its right stick


def test_an_analog_trigger_is_a_button_past_half_way(ecodes):
    pads = EvdevGamepads()
    pads.triggers["p"] = {ecodes.ABS_GAS: "r2"}
    dev = SimpleNamespace(absinfo=lambda code: SimpleNamespace(min=0, max=1023))
    values = (0, 300, 600, 900, 400, 300, 0, 800)
    events = [e for v in values for e in pads.translate("p", dev, raw(ecodes.EV_ABS, ecodes.ABS_GAS, v))]
    assert [(e.kind, e.name, e.value) for e in events] == [("button", "r2", 1), ("button", "r2", 0), ("button", "r2", 1)]


def test_digital_triggers_are_buttons(ecodes):
    pads = EvdevGamepads()
    events = pads.translate("p", None, raw(ecodes.EV_KEY, ecodes.BTN_TL2, 1))
    assert [(e.name, e.value) for e in events] == [("l2", 1)]
