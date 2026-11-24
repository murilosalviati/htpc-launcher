# HTPC Launcher

> [!WARNING]
> **Beta, not a finished product.** Versions are `0.x` pre-releases (`0.1.0-beta.1`, ...). It is built and tested on one home setup, parts of it have only been tested against simulated hardware, and the configuration format or install steps may still change. Back up `~/.config/htpc-launcher/apps.json` before updating.

A gamepad-driven home screen for a living-room PC running Ubuntu with GNOME on Wayland. It works with Xbox, 8BitDo and PlayStation controllers, and looks and behaves like a TV or console home screen.

![Launcher home screen](docs/preview.png)

*The app icons in these screenshots are placeholders. On a real install the launcher shows each app's own icon, or images you choose.*

## Features

- **A home screen made for the couch:**
  - one tile per app, with a glow and press animations;
  - the clock, the weather, gamepad and battery icons, and the network status across the top;
  - sizes that follow the screen, from 1080p to 4K.
- **Apps open in full screen and resume, never duplicate.** Selecting an app that is already running brings it back. Steam opens in Big Picture.
- **Shortcuts in any app:**

  | Shortcut | What it does |
  |---|---|
  | Home + LB + RB | Back to the launcher (pausing the video). |
  | Start + Select + LB + RB | Close the app. |
  | Start + Select + ↑ / ↓ | Volume, with GNOME's volume indicator. |

  The first two can be changed from Settings.
- **Over whatever is playing:** a short notice when a gamepad connects or disconnects, when a battery gets low, or when the internet drops or comes back. They show even over full-screen video and games.
- **Settings from the couch:**
  - apps (with an on-screen keyboard), background color, weather location, °C/°F, and English or Brazilian Portuguese;
  - **Bluetooth gamepad pairing**;
  - shortcuts;
  - Home Assistant.
- **Home Assistant (optional):** the gamepad wakes the TV and switches it to the right input, a button turns the TV off, and while it's off the gamepad only wakes it.
- **Small touches:** the mouse pointer hides while you use the gamepad, and Restart and Shut down are in the footer, with Cancel as the default.

The default configuration has VacuumTube (YouTube's TV interface), Jellyfin Desktop, Moonlight and Steam, all as Flatpaks.

<p>
  <img src="docs/settings.png" width="49%" alt="Settings">
  <img src="docs/gamepads.png" width="49%" alt="Settings → Gamepads">
</p>

## Quick start

1. Download the newest `htpc-launcher-<version>.tar.gz` from the [Releases page](https://github.com/murilosalviati/htpc-launcher/releases).
2. Extract it and install:

   ```bash
   tar xzf htpc-launcher-*.tar.gz && cd htpc-launcher-*/
   ./install.sh
   ```

3. Log out and back in. On a first install, then run `gnome-extensions enable htpc-launcher@htpc`.

The launcher starts by itself at login. Requirements, updating, and the notes for Jellyfin and Steam are in **[Installation](docs/installation.md)**.

## Documentation

| | |
|---|---|
| **[Installation](docs/installation.md)** | Requirements, installing, updating, app notes, uninstalling. |
| **[Using the launcher](docs/using.md)** | The home screen, notices, and every Settings menu. |
| **[Gamepads](docs/gamepads.md)** | Shortcuts, volume, changing the shortcuts, Bluetooth pairing, batteries. |
| **[Configuration](docs/configuration.md)** | The `apps.json` reference. |
| **[Home Assistant](docs/home-assistant.md)** | TV on/off with the gamepad and from the launcher. |
| **[Troubleshooting](docs/troubleshooting.md)** | Logs, common problems, working over SSH. |
| **[Development](docs/development.md)** | Architecture, the extension's D-Bus API, backends, tests, releases. |

What changed in each version is in the **[CHANGELOG](CHANGELOG.md)**.

## License

HTPC Launcher is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

App names such as YouTube, Jellyfin, Moonlight and Steam belong to their owners; this project is not affiliated with them.
