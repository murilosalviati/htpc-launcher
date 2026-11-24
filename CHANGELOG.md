# Changelog

The project is in beta: every `0.x` version is a pre-release, and the configuration format or install steps may still change.

## Unreleased

- **Gamepad batteries:** next to the gamepad icon, a battery icon (with a bolt while charging) for each wireless gamepad that reports its charge to Linux. Gamepads on a cable report none, so nothing is shown for them.

## 0.1.0-beta.3

Update by running `./install.sh` again, then **log out and back in once** so GNOME loads version 3 of the extension (needed for full-screen apps). Your `apps.json` is kept.

### New

- **Settings menu** (the gear in the footer), replacing "Edit apps": apps (edit mode), background color, weather location, temperature unit (°C or °F), language (switches right away, no restart) and a button to close the launcher (the guide button opens it again).
- **Weather** in the top-left corner: type a Brazilian CEP or a city name, confirm the place, and the launcher shows the temperature and an icon (clear, partly cloudy, cloudy, fog, rain, storm, snow; a moon at night). Data from Open-Meteo and ViaCEP, free and without an account. Updated every 30 minutes.
- **Clock in the middle** of the top bar.
- **Gamepad indicator** next to the network icon: lit when a gamepad is connected (USB, Bluetooth or wireless dongle), with the count when there is more than one. Virtual gamepads, like Steam Input's, are not counted.
- **Wired network icon:** a cable symbol when the machine is on a cable, Wi-Fi bars only on Wi-Fi.
- **Apps open in full screen**, through the GNOME extension (new `FullscreenOnOpen` method). Per app with `"fullscreen": false` in `apps.json`; Steam is off by default because Big Picture already is full screen.
- **Tile animations:** a glow that breathes behind the selected tile, a "button pressed" animation when you select one, and a green pulse while an app is opening.
- **Sizes follow the screen:** the clock, weather, status icons, hints and footer keep the same share of the screen on 1080p, 1440p or 4K, and start bigger than before.
- **Jellyfin Desktop works with a gamepad:** `launcher/install.sh` gives its Flatpak access to input devices and installs a gamepad map that matches any Xbox controller (its own map only matches "Xbox One") and leaves the guide button to the launcher.

### Fixed

- Steam failed with "Check your DISPLAY" when the launcher had been started from an SSH shell: programs now get the graphical session's `DISPLAY` and `XAUTHORITY`.
- An app closed right after opening came back as "opening…" for a while.
- At login the launcher window appeared about 50 seconds late, waiting for xdg-desktop-portal; it now shows up right away.
- The launcher's own icons were blurry when enlarged (an SVG was rasterized at 24 px and stretched); they are drawn from the vector at their size.

### Under the hood

- The code is split into a shared, OS-independent package (`htpc/`) and per-OS backends (`htpc/backends/`), with a documented plan for Windows.
- Tests: 30+ checks for the controller and backends, 90+ for the UI.

## 0.1.0-beta.2

- GPL-3.0-or-later license.
- Background color picker with 9 dark themes.

## 0.1.0-beta.1

- First public beta: gamepad home screen, resume instead of duplicate, guide and close-combo shortcuts, edit mode, restart and shut down, Steam in Big Picture, English and Brazilian Portuguese.
