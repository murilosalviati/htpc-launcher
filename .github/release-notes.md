> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

![Lights by room, further down the home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview-house.png)

## What's new in 0.1.0-beta.13

- **The shortcuts on screen:** hold **Start + Select** alone for a moment, in any app, and a panel lists the gamepad shortcuts over whatever is showing (full-screen video and games included), in your language and with your gamepad's button names. Let go and it's gone; a third button does its shortcut as usual. **Log out and back in after updating:** GNOME loads the extension's new version (8) at login.

### Fixed
- With the volume shortcut on the TV, a slow or unreachable Home Assistant held up every gamepad button, Home and Close included, for up to 10 seconds per step. The TV's volume now goes from a thread of its own, and quick presses add up into one request.
- Back in the launcher after a long time in an app, the screensaver could come on within seconds. Its wait now starts again whenever the launcher comes back.
- The controller's warnings and errors reach the journal with their priority (`journalctl --user -u htpc-controller -p warning`).

### Also in 0.1.0-beta.12
- **Settings → Audio** gathers the sound settings: what the volume shortcut changes (System or TV), the output, Bluetooth pairing. The TV's volume shows a TV on the indicator.

New [screenshots](https://github.com/murilosalviati/htpc-launcher#screenshots) of every part, in the README.

### Also in 0.1.0-beta.11

- **Continue watching** in Jellyfin's row, **LT / RT** to switch tabs, the **screensaver** (closed by any button or by turning a gamepad on), the **forecast** under the lights, **lights by room side by side**, **reordering apps** with LB / RB.
- **PlayStation controllers:** ✕ ○ □ △ and L1 / R1 / L2 / R2 in the hints.
- **Wake the PC Steam streams from** when it opens: give the Steam app a `wake_on_lan` in `apps.json`. See [Configuration](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/configuration.md#apps).

Gamepads drawn with their battery, the TV input button and turning the gamepads off with the TV came in [0.1.0-beta.10](https://github.com/murilosalviati/htpc-launcher/releases/tag/v0.1.0-beta.10).

The new home screen arrived in [0.1.0-beta.8](https://github.com/murilosalviati/htpc-launcher/releases/tag/v0.1.0-beta.8): films and series from Jellyfin, Steam games, your lights, the power menu.

This product uses the TMDB API but is not endorsed or certified by TMDB.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.13.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`. `SHA256SUMS` lets you check it: `sha256sum -c SHA256SUMS`.
2. Run `./install.sh` inside the extracted folder. An existing `apps.json` is kept.
3. **Log out and back in** if you are coming from beta.5 or older: GNOME only loads the extension's version 7 at login. On a first install, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself at login.

From beta.6 on, updates can also be installed from **Settings → Updates**.

Requirements:
- **System:** Ubuntu with GNOME on Wayland. It's tested on GNOME Shell 50.
- **Packages:** the installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing.
- **Optional:**
  - a Bluetooth adapter, for pairing;
  - PipeWire or PulseAudio, for the volume shortcut and audio output;
  - Home Assistant, for TV control, cinema mode and your lights;
  - Jellyfin (and a free TMDB key), for films and series on the home screen.

See the [documentation](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/README.md) for everything else.
