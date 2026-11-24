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


class Media(ABC):
    @abstractmethod
    def pause_all(self):
        """Pause every media player that is playing. Returns their names."""


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
        """A Gamepads reader."""

    @abstractmethod
    def apps(self):
        """An AppCatalog."""

    @abstractmethod
    def system(self):
        """A System."""
