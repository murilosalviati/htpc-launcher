> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.4

- **Gamepad batteries:** next to the gamepad icon, a battery icon for each wireless gamepad that reports its charge, from empty (red) to full, with a bolt while charging. Gamepads on a cable report no charge, so nothing is shown for them.

Version 0.1.0-beta.3, a day earlier, brought the Settings menu, weather, full-screen apps, tile animations, sizes that follow the screen and gamepad support in Jellyfin Desktop. The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.4.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`
2. Run `./install.sh` inside the extracted folder. An existing `apps.json` is kept.
3. **Log out and back in** so GNOME loads the extension (version 3; if you are coming from 0.1.0-beta.3 it did not change and no new login is needed). On a first install, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself at login.

Requires Ubuntu with GNOME on Wayland (tested on GNOME Shell 50). The installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing. The default apps (VacuumTube, Jellyfin Desktop, Moonlight, Steam) are expected as Flatpaks; change them from Settings → Apps.

**Tip for 4K TVs:** if the TV only gets 4K at 30 Hz (common with integrated GPUs), a 60 Hz mode like 2560×1440 makes everything, Steam's Big Picture especially, much smoother. The launcher adapts to the new size by itself.

See the [README](https://github.com/murilosalviati/htpc-launcher#readme) for configuration and troubleshooting.
