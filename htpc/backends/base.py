# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Murilo Salviati
"""What an operating-system backend must provide.

The launcher UI and the controller service only talk to the OS through these
classes. To support a new OS, implement them in htpc/backends/<os>/ and add it
to htpc.backends.get_backend().

All app ids are compared case-insensitively. An app id is whatever names a
window on that OS (Linux: Flatpak id, .desktop id or WM_CLASS; Windows: the
executable name or the AppUserModelID, for example).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# Normalized gamepad buttons. Backends map their raw codes onto these names.
BUTTONS = ("a", "b", "x", "y", "start", "select", "l1", "r1", "guide",
           "up", "down", "left", "right")
# Normalized axes: the left stick, from -1.0 (left/up) to 1.0 (right/down).
AXES = ("lx", "ly")


@dataclass
class Window:
    app_id: str                 # the window's main name
    ids: list                   # every name the window answers to, lowercase
    title: str = ""
    pid: int = 0
    focused: bool = False


@dataclass
class IconRef:
    """An icon without tying it to a UI toolkit: theme names to try in order, or an image file."""
    names: tuple = ()
    path: str = None


@dataclass
class InstalledApp:
    """An application the user can add as a shortcut."""
    id: str                     # window name, also used as the shortcut's "id"
    name: str
    launch: list                # command that starts it
    icon: IconRef = field(default_factory=IconRef)
    desktop: str = None         # OS-specific entry the icon comes from (Linux: .desktop id)
    extra_ids: list = field(default_factory=list)


@dataclass
class Battery:
    """Charge of a wireless gamepad, as the OS reports it."""
    name: str                   # the gamepad's name
    percent: int = None         # 0..100, or None when only a level is known
    level: str = ""             # "full", "high", "normal", "low", "critical" (when percent is None)
    charging: bool = False

    @property
    def bars(self):
        """0..4, for the icon."""
        if self.percent is not None:
            p = self.percent
            return 4 if p >= 90 else 3 if p >= 60 else 2 if p >= 35 else 1 if p >= 15 else 0
        return {"full": 4, "high": 3, "normal": 2, "low": 1, "critical": 0}.get(self.level, 2)


@dataclass
class GamepadEvent:
    device: str                 # stable id of the gamepad while it is connected
    kind: str                   # "button", "axis" or "disconnected"
    name: str                   # one of BUTTONS or AXES
    value: float                # buttons: 1 pressed, 0 released; axes: -1.0..1.0


class WindowControl(ABC):
    """Finding, raising and closing app windows.

    Not shared between threads: create one per thread with Backend.window_control().
    Methods return None when the OS side is not reachable (e.g. the GNOME extension
    is not running), so callers can tell "no" from "could not ask".
    """

    @abstractmethod
    def windows(self):
        """List[Window] of normal app windows."""

    def focused(self):
        ws = self.windows()
        return None if ws is None else next((w for w in ws if w.focused), None)

    @abstractmethod
    def is_running(self, app_id):
        """True if the app has a window."""

    @abstractmethod
    def activate(self, app_id, preferred_titles=()):
        """Raise the app's window (the first matching title, else the most recent one).
        False if the app has no window."""

    @abstractmethod
    def close(self, app_id):
        """Ask the app's windows to close. Returns how many were asked."""

    @abstractmethod
    def show_launcher(self):
        """Raise the launcher. False if it is not running."""

    def notify(self, title, body, icon_path, seconds=6):
        """Show a short notice over whatever is on screen, full-screen apps included.
        None if the OS side cannot do it."""
        return None

    def show_osd(self, icon_name, level):
        """The desktop's own on-screen level indicator (volume), level 0..1.
        Returns True when shown; None/False when the desktop can't."""
        return None

    def hide_pointer(self):
        """Hide the mouse pointer on the whole screen until the mouse moves again.
        True if hidden, None if the OS side cannot do it."""
        return None

    def fullscreen_on_open(self, app_id, seconds=60):
        """Put the app's windows in full screen, including the ones it opens in the
        next `seconds`. Returns how many windows went full screen right away, or None
        if the OS side cannot do it."""
        return None


class Media(ABC):
    @abstractmethod
    def pause_all(self):
        """Pause every media player that is playing. Returns their names."""

    def playback(self):
        """"playing" if any player is playing, else "paused" if any is paused,
        else "stopped" (also when there are no players). None if it can't tell."""
        return None


class Gamepads(ABC):
    """Reads every connected gamepad without taking the buttons away from other apps."""

    @abstractmethod
    def poll(self, timeout):
        """Wait up to `timeout` seconds and return a list of GamepadEvent.
        Also picks up gamepads that were plugged in or removed."""

    def available(self):
        """False when this backend cannot read gamepads here (e.g. a missing library)."""
        return True

    def connected(self):
        """Names of the physical gamepads connected right now (USB, Bluetooth or a
        wireless dongle), one entry per gamepad. Virtual gamepads, like the ones
        Steam Input creates, are left out. Updated by poll()."""
        return []

    def batteries(self):
        """List[Battery] for the connected gamepads that report one (wireless ones,
        usually; a gamepad on a cable reports nothing)."""
        return []


class AppCatalog(ABC):
    @abstractmethod
    def installed(self):
        """List[InstalledApp], sorted by name, for the "choose application" list."""

    @abstractmethod
    def describe(self, app):
        """Display name of the application behind a shortcut (an apps.json entry), or None."""

    @abstractmethod
    def icon_for(self, app):
        """IconRef for a shortcut: its "icon" setting, else the icon the app installed."""

    def icon_dirs(self):
        """Extra folders the UI should search for theme icons."""
        return []


class System(ABC):
    @abstractmethod
    def spawn(self, command):
        """Start a program detached from us. True if it started."""

    @abstractmethod
    def force_close(self, app_id, pid):
        """Last resort when an app ignores the request to close."""

    @abstractmethod
    def reboot(self):
        """Restart the machine."""

    @abstractmethod
    def power_off(self):
        """Shut the machine down."""

    def connectivity(self):
        """Whether the internet works: "full", "limited" (no internet, captive
        portal...), "none" (not connected), or None when the OS cannot tell."""
        return None

    def change_volume(self, step):
        """Raise (step > 0) or lower the output volume by step (0.05 = 5 points),
        unmuting when raising. Returns (level 0..1, muted) or None if it can't."""
        return None

    def connection_kind(self):
        """How the machine reaches the network right now: "wired", "wifi", or None when
        there is no connection or the OS cannot tell. The launcher picks its icon from this."""
        return None


@dataclass
class AudioOutput:
    id: str                     # OS-specific
    name: str                   # as shown to people ("TV (HDMI)", "JBL Flip 5")
    current: bool = False       # where the sound goes now
    bluetooth: bool = False


class Audio:
    """Where the sound goes. The default: can't tell or change it."""

    def outputs(self):
        """[AudioOutput], the current one marked."""
        return []

    def set_output(self, output_id):
        """Send all sound to this output from now on (playing streams included)."""
        raise RuntimeError("can't change the audio output here")


@dataclass
class DisplayMode:
    id: str                     # OS-specific
    width: int
    height: int
    refresh: float              # Hz
    current: bool = False

    def label(self):
        return f"{self.width}×{self.height} · {round(self.refresh)} Hz"

    def key(self):
        """"3840x2160@30": how apps.json names a mode."""
        return f"{self.width}x{self.height}@{round(self.refresh)}"


def parse_mode_key(text):
    """"3840x2160@30" → (3840, 2160, 30.0); the rate is optional ("3840x2160")."""
    size, _, rate = str(text).lower().partition("@")
    w, _, h = size.partition("x")
    return int(w), int(h), (float(rate) if rate else None)


def pick_mode(modes, key):
    """The mode in `modes` that best matches an apps.json key, or None."""
    try:
        w, h, rate = parse_mode_key(key)
    except ValueError:
        return None
    same = [m for m in modes if m.width == w and m.height == h]
    if not same:
        return None
    if rate is None:
        return max(same, key=lambda m: m.refresh)
    return min(same, key=lambda m: abs(m.refresh - rate))


class Display:
    """The screen's resolution and refresh rate. The default: can't change it."""

    def modes(self):
        """[DisplayMode] of the main screen, the current one marked."""
        return []

    def default_mode(self):
        """The mode the desktop is set to keep (what to go back to), or None."""
        return None

    def apply(self, mode):
        """Switch to mode until told otherwise (not saved as the desktop's setting)."""
        raise RuntimeError("can't change the resolution here")


@dataclass
class BluetoothDevice:
    address: str
    name: str
    paired: bool = False
    connected: bool = False
    gamepad: bool = False       # looks like a gamepad (icon, device class or name)
    audio: bool = False         # headphones, a speaker, a soundbar...
    kind: str = ""              # "gamepad", "keyboard", "mouse", "audio" or "" (anything else)
    path: str = ""              # OS-specific handle
    has_name: bool = True       # False while only the address is known


class Bluetooth:
    """Pairing gamepads. The default is "no Bluetooth here"; backends override it.
    Every call may block (run them off the UI thread) and may raise on errors."""

    def available(self):
        """Is there a Bluetooth adapter?"""
        return False

    def start_search(self):
        """Power the adapter on and start looking for devices in pairing mode."""
        raise RuntimeError("no Bluetooth")

    def stop_search(self):
        """Stop looking (also called when the pairing screen closes)."""

    def devices(self):
        """[BluetoothDevice]: known and found devices, connected and paired first."""
        return []

    def pair(self, address):
        """Pair, trust (so it reconnects by itself) and connect."""
        raise RuntimeError("no Bluetooth")

    def forget(self, address):
        """Remove a paired device."""
        raise RuntimeError("no Bluetooth")


class Backend(ABC):
    name = "?"

    @abstractmethod
    def window_control(self):
        """A new WindowControl (one per thread)."""

    @abstractmethod
    def media(self):
        """A Media."""

    @abstractmethod
    def gamepads(self):
        """The Gamepads reader: always the same one per backend, since only poll()
        keeps its list of gamepads up to date."""

    @abstractmethod
    def apps(self):
        """An AppCatalog."""

    @abstractmethod
    def system(self):
        """A System."""

    def bluetooth(self):
        """A Bluetooth (by default: none)."""
        return Bluetooth()

    def display(self):
        """A Display (by default: fixed)."""
        return Display()

    def audio(self):
        """An Audio (by default: fixed)."""
        return Audio()
