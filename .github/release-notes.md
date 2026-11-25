> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.8

**A new home screen.** Without Jellyfin, Steam and Home Assistant set up, it looks as before: the apps alone in the middle.

### A row that follows the app in focus
- **Jellyfin:** tabs **Explore**, **Series** and **Films**. Explore shows what's new and popular on [TMDB](https://www.themoviedb.org/) **and is in your library**, matched by the TMDB id Jellyfin keeps. Old favourites that trend without anything new are left out.
- **Steam:** **Games**, last played first, including games streamed from another computer with Remote Play. An installed game starts right away; a streamed one opens its Steam page, where Stream is.
- **RB / LB** turn the page, five cards at a time.
- Set up in **Settings → Jellyfin**: address, API key, user, and a free TMDB key.

### Your lights below the apps (Home Assistant)
- Go down from the apps: lights, switches and scenes. **Ⓐ** turns one on or off.
- **Hold Ⓐ** on a light for brightness, white temperature and colour.
- **Separate by room**, and choose which lights show, in Settings → Home Assistant.

### The rest of the screen
- The clock at the top left, with the date and the weather on one line.
- **One power button:** Turn off the TV, Restart, Shut down. Turning off the TV puts the launcher back on its start for next time.
- No more button reminders at the bottom.

This product uses the TMDB API but is not endorsed or certified by TMDB.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.8.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`. `SHA256SUMS` lets you check it: `sha256sum -c SHA256SUMS`.
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
