> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.3

- **Settings menu** (the gear in the footer): apps, background color, weather location, °C or °F, language (applies right away) and a button to close the launcher.
- **Weather** in the top-left corner, from a Brazilian CEP or a city name (Open-Meteo and ViaCEP, no account needed), with day and night icons.
- **Clock in the middle**, a **gamepad indicator** (with the count when there is more than one) and a **cable icon** on wired connections.
- **Apps open in full screen** through the GNOME extension (Steam's Big Picture excepted).
- **Tile animations:** breathing glow on the selected tile, a "button pressed" animation, and a green pulse while an app opens.
- **Sizes follow the screen**, from 1080p to 4K, with sharp vector icons at any size.
- **Jellyfin Desktop works with a gamepad:** the installer gives its Flatpak access to input devices and adds a map for any Xbox controller.

### Fixed

- Steam's "Check your DISPLAY" error when the launcher was started from SSH.
- An app closed right after opening showing "opening…" again.
- The launcher appearing ~50 s late at login.
- Blurry icons when enlarged.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.3.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`
2. Run `./install.sh` inside the extracted folder. An existing `apps.json` is kept.
3. **Log out and back in** so GNOME loads the extension (version 3 in this release). On a first install, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself at login.

Requires Ubuntu with GNOME on Wayland (tested on GNOME Shell 50). The installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing. The default apps (VacuumTube, Jellyfin Desktop, Moonlight, Steam) are expected as Flatpaks; change them from Settings → Apps.

**Tip for 4K TVs:** if the TV only gets 4K at 30 Hz (common with integrated GPUs), a 60 Hz mode like 2560×1440 makes everything, Steam's Big Picture especially, much smoother. The launcher adapts to the new size by itself.

See the [README](https://github.com/murilosalviati/htpc-launcher#readme) for configuration and troubleshooting.
