> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.9

### Bluetooth Xbox controllers work
- **Pairing** no longer fails with "Authentication Failed": the launcher answers the controller's pairing request itself, and tries once more if the first attempt is refused.
- **Once paired**, newer Xbox controllers (Bluetooth LE) were ignored, taken for Steam Input's virtual gamepads. They control the launcher and the shortcuts now.
- A refused pairing says what to do, and long messages no longer run off the screen.

### Home screen
- **Explore** leaves out shows that never stop (SNL, SpongeBob...): only series that premiered in the last 8 years count as new, and kids', news, soap and talk shows don't.
- **Lights by room** follow the order you chose, and lights can have **names of your own** (`names` in `apps.json`), such as a dashboard's short names.

The new home screen arrived in [0.1.0-beta.8](https://github.com/murilosalviati/htpc-launcher/releases/tag/v0.1.0-beta.8): films and series from Jellyfin, Steam games, your lights, the power menu.

This product uses the TMDB API but is not endorsed or certified by TMDB.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.9.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`. `SHA256SUMS` lets you check it: `sha256sum -c SHA256SUMS`.
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
