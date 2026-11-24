# Changelog

The project is in beta: every `0.x` version is a pre-release, and the configuration format or install steps may still change.

## Unreleased

- **Volume from the gamepad: Start + Select + ↑ / ↓**, 5 points per press, repeating while the arrow is held, up to 100%; raising unmutes. GNOME's own volume indicator shows the level over any app, full-screen ones included, like the notices (GNOME extension version 6: log out and back in after updating). The launcher ignores the arrows while Start + Select are held, and a custom shortcut can't be just Start + Select.
- **Back to the launcher is now Home + LB + RB** (PS + L1 + R1, Home + L + R). The guide button alone is left to the apps, so Steam's menu works again instead of throwing you back to the launcher.
- **Pair Bluetooth gamepads from Settings → Gamepads → Pair a gamepad.** The launcher powers the adapter on and searches (BlueZ over D-Bus, no extra packages); gamepads in pairing mode show up in a list (other devices are left out), and picking one pairs, trusts and connects it, so it reconnects by itself later. Paired ones can be forgotten from the same list. Without an adapter the screen explains the alternatives (cable, the gamepad's own USB receiver).
- **Settings → Gamepads:** change the "back to the launcher" and "close the app" combos by holding the new buttons for 2 seconds (hold B alone to cancel). A combo needs two buttons or more, and the two combos can't contain each other. The controller service picks up changes right away; the footer hints show the current combos.
- **"Turn off TV" button** in the middle of the footer, shown only when switched on in Settings → Home Assistant (off by default): sends "tv_off" to the same webhook, and the automation turns the TV off. Any gamepad button wakes it again: right after this button the next press is sent at once instead of waiting for the once-a-minute limit, and the automation ignores activity for 15 seconds after the TV goes off so the press on the button itself does not turn it back on. The hints at the bottom left now take two lines to leave the middle free.
- **The gamepad is ignored while the TV is off.** With a Home Assistant long-lived access token (in apps.json, as "token") and the TV chosen in Settings → Home Assistant → TV, the controller service checks the TV's state every 3 seconds. While it is off, the launcher and the shortcuts ignore the gamepad: the first press only wakes the TV (asking again if it is still off 8 seconds later). If Home Assistant can't be reached or the TV's state is unknown, nothing is blocked. Apps that read the gamepad themselves (Steam, Jellyfin) still get it.
- **Home Assistant guide:** [docs/home-assistant.md](docs/home-assistant.md) covers setup, the events, troubleshooting and security. The example automation now treats webOS's "idle", "playing" and "paused" as on.
- **Settings → Home Assistant:** on/off, the address and the webhook id (typed on the on-screen keyboard, which gets a ": / _" row for them), the "Turn off TV" button and a connection test. No need to edit apps.json by hand.
- **Home Assistant:** the controller service calls a webhook when a gamepad connects or a button is pressed (at most once a minute), so an automation can turn the TV on and switch it to the HTPC input. Example automation for LG webOS TVs in `extras/home-assistant/wake-tv.yaml`; configured with `"home_assistant"` in `apps.json`.
- **On-screen notices over whatever is playing** (Moonlight, YouTube, Jellyfin, games): a gamepad connected or disconnected, a gamepad battery low (20%) or almost empty (10%), the internet dropping, limited or back. They appear in the top-right corner for a few seconds, without taking the focus or pausing anything, sized for the screen. A switch in Settings turns them off. Drawn by the GNOME extension (version 5: log out and back in once after updating); test one with `gnome-extension/test.sh notify "Title" "text"`.
- **The mouse pointer hides when the gamepad is used**, on the whole screen (apps included), and comes back as soon as the mouse moves. Needs version 4 of the GNOME extension: log out and back in once after updating.
- **Fixed:** on Xbox controllers (and others on Xbox drivers, like 8BitDo in XInput mode) X and Y were swapped, so Y deleted on the on-screen keyboard instead of typing a space. Xbox drivers send X and Y with the kernel codes meant for the opposite positions; the launcher now recognizes them (by driver or by name) and swaps them back. PlayStation and Nintendo-style pads already followed the positions and are unchanged.

## 0.1.0-beta.4

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
