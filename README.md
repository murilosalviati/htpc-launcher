# HTPC Launcher

> [!WARNING]
> **Beta, not a finished product.** Versions are `0.x` pre-releases (`0.1.0-beta.1`, ...). It is built and tested on one home setup, parts of it have only been tested against simulated hardware, and the configuration format or install steps may still change. Back up `~/.config/htpc-launcher/apps.json` before updating.

A gamepad-driven home screen for a living-room PC running Ubuntu with GNOME on Wayland. It works with Xbox, 8BitDo and PlayStation controllers, and looks and behaves like a TV or console home screen.

![Launcher home screen](docs/preview.png)

*The app icons in this screenshot are placeholders. On a real install the launcher shows each app's own icon, or images you choose.*

## Features

- **Full-screen home screen** with one tile per app. Across the top:
  - on the left, the current weather (icon, temperature and place), once you set a location;
  - in the middle, the clock and date;
  - on the right, a gamepad icon that lights up when a gamepad is connected (USB, Bluetooth or wireless dongle) and shows how many there are when there is more than one, and the network icon: a cable symbol on a wired connection, Wi-Fi bars on Wi-Fi. It is just an icon while you are online and only shows text when the connection is limited or down.
- **Resume, never duplicate:** selecting an app that is already running brings its existing window back instead of starting a second copy.
- **Guide button** (Xbox / Home / PS): pauses the video that is playing, if any, and returns to the launcher. The app keeps running behind it.
- **Start + Select + L1 + R1:** closes the focused app and returns to the launcher. For game streaming apps like Moonlight, the first press ends the stream (Moonlight's own shortcut) and a second press within 15 seconds closes the app.
- **Settings** (the gear in the footer): apps, background color, weather location, temperature unit (°C or °F) and language, all from the couch.
- **Weather:** type a Brazilian CEP or a city name; the launcher finds the place, asks you to confirm it, and shows the conditions, updated every 30 minutes, with a moon instead of the sun at night. It uses [Open-Meteo](https://open-meteo.com/) and [ViaCEP](https://viacep.com.br/), which are free and need no account. Leave the location empty to hide it.
- **Edit mode** (Settings → Apps): add, edit and remove shortcuts.
  - Type names on an on-screen keyboard driven by the gamepad (Ⓧ deletes, Ⓨ types a space). A physical keyboard works too.
  - Pick the application from the list of installed apps, including Flatpaks.
  - Pick the icon: the app's own, or any image in `~/.local/share/htpc-launcher/app-icons/`.
  - The grid wraps onto more rows after 5 apps and reflows when you remove one.
- **Background colors:** 9 dark themes (Midnight, Ocean, Forest, Aurora, Plum, Wine, Ember, Graphite, Black), previewed live as you move between them.
- **Restart and shut down** buttons in the footer, both with a confirmation that defaults to Cancel.
- **English and Brazilian Portuguese** on-screen text, switched in Settings without restarting.
- **Steam opens in Big Picture.** It starts with `-gamepadui`, and if it is already running in desktop mode, the launcher switches it to Big Picture when you select it.

The default configuration has VacuumTube (YouTube's TV interface), Jellyfin Desktop, Moonlight and Steam, all as Flatpaks.

## How it works

The code is split into a shared, OS-independent part and a backend per operating system. Today there is a Linux backend (GNOME on Wayland); a Windows backend is planned and its design is written down in `htpc/backends/windows/`.

On Wayland, a regular program cannot raise another app's window or find out which window has focus, so on Linux there is also a small GNOME Shell extension that does it.

| Folder | What it is |
|---|---|
| `gnome-extension/` | The `htpc-launcher@htpc` GNOME Shell extension. It runs inside GNOME and exposes window control on the session bus (`org.htpc.Launcher`): list windows, raise or close an app's windows, show the launcher. |
| `controller/` | The background service that reads the gamepads and runs the shortcuts (a systemd user service on Linux). |
| `launcher/` | The home screen UI in GTK 4 (`launcher.py`), with the settings menu in `settings.py` and edit mode in `editor.py`. It only reaches the OS through the backend. |
| `htpc/` | The shared Python package: `apps.json` handling (`config.py`), file locations per OS (`paths.py`), the guide and close-combo rules (`shortcuts.py`), on-screen text (`i18n.py`), background colors (`themes.py`) and the weather lookup (`weather.py`). |
| `htpc/backends/` | Everything that talks to the operating system, behind the interface in `base.py`: window control, media pausing, gamepad input, the installed-apps list, and starting, force-closing, restart and shut down. `linux/` implements it; `windows/` is a documented placeholder. |
| `config/apps.json` | The example configuration, installed to `~/.config/htpc-launcher/apps.json`. |
| `tests/` | Tests that run against a fake GNOME extension and a fake media player. |

## Requirements

- Ubuntu with GNOME on Wayland. Tested on GNOME Shell 50; the extension declares support for 47 to 51.
- `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0`. The install scripts install whichever are missing.
- The apps you want to launch. The default `apps.json` expects these Flatpaks: `rocks.shy.VacuumTube`, `org.jellyfin.JellyfinDesktop`, `com.moonlight_stream.Moonlight` and `com.valvesoftware.Steam`.

## Install

Download the newest beta from the [Releases page](https://github.com/murilosalviati/htpc-launcher/releases) (they are marked as pre-releases), extract it and run:

```bash
./install.sh
```

It installs the three parts below in order. The first time, log out and back in afterwards so GNOME loads the extension, then run `gnome-extensions enable htpc-launcher@htpc`.

To install the parts one by one instead, in this order:

```bash
gnome-extension/install.sh   # then log out and back in, and run:
                             #   gnome-extensions enable htpc-launcher@htpc
controller/install.sh
launcher/install.sh          # starts by itself on the next login; to start it now:
                             #   gtk-launch htpc-launcher
```

With auto-login, logging out may not log you back in; `sudo systemctl restart gdm` does, but it closes every open app.

In Steam's controller settings, turn off the guide button's Steam function so it does not react together with the launcher.

To use your own icons, put PNG files in an `app-icons/` folder at the root of the repository before running `launcher/install.sh`, or copy them straight to `~/.local/share/htpc-launcher/app-icons/`. That folder is in `.gitignore`.

## Configuration: `apps.json`

You can change everything from the launcher's Settings, or by hand:

```json
{
  "name": "YouTube",
  "id": "rocks.shy.VacuumTube",
  "icon": "~/.local/share/htpc-launcher/app-icons/youtube.png",
  "launch": ["flatpak", "run", "rocks.shy.VacuumTube", "--ozone-platform=wayland"],
  "pause_on_home": true
}
```

| Field | What it does |
|---|---|
| `name` | The label under the tile. |
| `id` | The app's window name: its Flatpak id, `.desktop` id or WM_CLASS. `gnome-extension/test.sh` lists the names of every open window. |
| `extra_ids` | Other names for the same window. |
| `launch` | The command that starts the app. |
| `on_resume` | A command to run when the app is already running and you select it again, such as switching Steam to Big Picture. |
| `close` | The command that closes the app, for apps that only hide when their window closes (Steam: `-shutdown`). |
| `close_timeout` | Seconds to wait before forcing the app to close. The default is 3. |
| `pause_on_home` | Pause media (MPRIS) when the guide button is pressed in this app. |
| `close_on_second_press` | The first close combo goes to the app itself; the second one closes it. |
| `preferred_windows` | For apps with several windows: titles to bring to the front, in order of preference. Without it, the most recently used window comes up. |
| `icon` | A theme icon name or an image path. Without it, the launcher uses the icon the app installed. |
| `desktop` | The `.desktop` file to take the icon from, when it differs from `id`. |

At the top level, `language` sets the on-screen text (`en` or `pt-BR`), `background` sets the background color (`midnight`, `ocean`, `forest`, `aurora`, `plum`, `wine`, `ember`, `graphite` or `black`; see `htpc/themes.py`), `temperature_unit` is `celsius` or `fahrenheit`, `weather` holds the place chosen in Settings (`query`, `name`, `latitude`, `longitude`; remove it to hide the weather), and `launcher.launch` is the command the service uses to start the launcher if it is not running. `launcher/install.sh` fills it in.

Older versions of this project used Portuguese field names (`nome`, `abrir`...). They are converted automatically the first time the launcher starts, and the on-screen text stays in Portuguese for those installs.

## Troubleshooting

```bash
gnome-extension/test.sh                           # open windows and the focused app
gnome-extension/test.sh launcher                  # bring the launcher to the front
journalctl --user -fu htpc-controller             # what the gamepad service is doing
journalctl --user -f -o cat /usr/bin/gnome-shell  # errors from the extension
```

Over SSH, first export `XDG_RUNTIME_DIR=/run/user/$(id -u)`, `DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus` and `WAYLAND_DISPLAY=wayland-0` so the commands reach the graphical session.

## Porting to another operating system

Implement the classes in `htpc/backends/base.py` (`WindowControl`, `Media`, `Gamepads`, `AppCatalog`, `System`) in `htpc/backends/<os>/`, and add the OS to `get_backend()` in `htpc/backends/__init__.py`. The launcher UI, edit mode, configuration and shortcut rules then work unchanged. `htpc/backends/windows/__init__.py` lists how each piece would be done on Windows.

## Tests

```bash
dbus-run-session -- python3 tests/test_controller.py
xvfb-run -s "-screen 0 1920x1080x24" dbus-run-session -- python3 tests/test_launcher.py
```

`tests/test_controller.py` covers the shortcut rules, the Linux backend's D-Bus and evdev handling, and config migration. `tests/test_launcher.py` drives the UI with normalized gamepad events and explains the files it expects in `HOME` for the icon and app-list checks.

## License

HTPC Launcher is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

App names such as YouTube, Jellyfin, Moonlight and Steam belong to their owners; this project is not affiliated with them.
