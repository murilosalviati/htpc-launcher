HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

## Install

1. Download **htpc-launcher-VERSION.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`
2. Run `./install.sh` inside the extracted folder.
3. The first time, log out and back in so GNOME loads the extension, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself on that login.

Requires Ubuntu with GNOME on Wayland (tested on GNOME Shell 50). The installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing. The default apps (VacuumTube, Jellyfin Desktop, Moonlight, Steam) are expected as Flatpaks; you can change them from the launcher's edit mode.

## What's in it

- Full-screen home screen with app tiles, a clock and a network indicator.
- Selecting a running app brings its window back instead of opening a second copy.
- Guide button pauses the video and returns home; Start + Select + L1 + R1 closes the app.
- Edit mode to add, edit and remove apps with the gamepad, including an on-screen keyboard.
- Restart and shut down from the couch, with confirmation.
- Steam always comes up in Big Picture.
- English and Brazilian Portuguese on-screen text.

See the [README](https://github.com/murilosalviati/htpc-launcher#readme) for configuration and troubleshooting.
