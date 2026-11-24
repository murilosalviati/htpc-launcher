> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.5

> **Heads-up:** the shortcut to go back to the launcher is now **Home + LB + RB** (PS + L1 + R1, Home + L + R). The guide button alone is left to the apps, so Steam's menu works again.

### Gamepads
- **Volume from the gamepad:** Start + Select + ↑ / ↓. Each press changes it by 5 points, and holding the arrow keeps going. GNOME's volume indicator shows the level over any app, full-screen ones included.
- **Change the shortcuts** in Settings → Gamepads: hold the new buttons for 2 seconds. The footer hints follow along.
- **Pair Bluetooth gamepads** from Settings → Gamepads → Pair a gamepad. Gamepads in pairing mode show up in a list; pick one and it's paired, trusted and connected. Paired ones can be forgotten from the same list.
- **The mouse pointer hides** while you use the gamepad, and comes back when the mouse moves.
- **Fixed:** X and Y were swapped on Xbox controllers, and on others using Xbox drivers.

### Notices
- **Notices over whatever is playing**, in the top-right corner, even over full-screen video and games:
  - a gamepad connected or disconnected;
  - a battery low (20%) or almost empty (10%);
  - the internet dropping, limited, or coming back.

  A switch in Settings turns them off.

### Home Assistant (optional)
- **The gamepad wakes the TV** and switches it to the HTPC's input.
- **A "Turn off TV" button** in the middle of the footer.
- **While the TV is off, the gamepad only wakes it.** The launcher and the shortcuts ignore it, so nothing opens on a dark screen. This needs a long-lived access token.
- **Settings → Home Assistant:** the address, the webhook, the TV, the button, and a connection test.
- **Guide:** [docs/home-assistant.md](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/home-assistant.md), with an example automation for LG webOS TVs.

### Documentation
- **A full guide** in [docs/](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/README.md): installation, using the launcher, gamepads, configuration, Home Assistant, troubleshooting and development.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.5.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`
2. Run `./install.sh` inside the extracted folder. An existing `apps.json` is kept.
3. **Log out and back in.** This version updates the GNOME extension to version 6, and GNOME only loads it at login. On a first install, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself at login.

Requirements:
- **System:** Ubuntu with GNOME on Wayland. It's tested on GNOME Shell 50.
- **Packages:** the installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing.
- **Optional:**
  - a Bluetooth adapter, for pairing;
  - PipeWire or PulseAudio, for the volume shortcut;
  - Home Assistant, for TV control.

See the [documentation](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/README.md) for everything else.
