# Changelog

The project is in beta: every `0.x` version is a pre-release, and the configuration format or install steps may still change.

## Unreleased

**A new home screen.** The apps are now the middle row of three:

- **A row of cards above the apps that follows the app in focus.** With Jellyfin in focus, three tabs: **Explore** (this week's popular titles on TMDB that are in your Jellyfin library, matched by the TMDB id Jellyfin keeps; without a TMDB key, what was added lately), **Series** and **Films** (added lately). With Steam in focus, **Games**: last played first, read from Steam's own files (Flatpak or native, every library folder), including games streamed from another computer (names from the Steam store, cached; covers from Steam's cache or image servers). An installed game starts through Steam; a streamed one opens its Steam page, where Stream is. Other apps show nothing, and the space stays so nothing jumps. **RB / LB** turn the page (five cards a page) when tapped alone. Selecting a film or series opens the Jellyfin app. Set up in the new Settings → Jellyfin (address, API key, user, TMDB key, test).
- **Home (Home Assistant)** below the apps, reached by going down: lights and switches by room, and scenes. Ⓐ turns one on or off (shown at once), Ⓨ on a dimmable light opens its brightness (−/+ by 10%). Every light by default; choose in Settings → Home Assistant → Lights on the home screen. Needs the address and the token. States are read every 5 seconds while the launcher is in front.
- **The clock moved to the top left**, with the weather next to it.
- **One power button** at the top right, next to Settings, replaces Restart, Shut down and the footer's "Turn off TV". It opens a menu: Turn off the TV (when Home Assistant is set up, and selected first), Restart the computer, Shut down the computer, Cancel. Turning off the TV also puts the launcher back on its start (menus closed, first app selected, scrolled up) for the next time. The menu is the confirmation; restart and shut down never start selected. The `tv_off_button` setting is gone.
- **The weather moved onto the date's line**, in its style: "Wednesday, 25/11/2026 • 24°" and the icon. Dates read dd/mm/yyyy.
- **Explore shows what's new**, not all-time favourites: trending films and series from the last 18 months (`recent_days` in `tmdb`), series with new episodes this week, films in cinemas.
- **Lights: hold Ⓐ** (or Ⓨ) for a panel with brightness, white temperature and colour, as far as the light supports them; **Separate by room** puts each room's name over its lights.
- The icons in the round buttons at the top right are centred.
- **No more button reminders** at the bottom left; the bottom of the screen only explains edit mode while it's on.
- Without Jellyfin and Home Assistant set up, the screen looks as before: the apps alone in the middle.

## 0.1.0-beta.7

- **Fixed:** the beta.6 package still called itself beta.5 inside (`htpc.__version__`), so Settings → Updates kept offering beta.6 after it was installed. A unit test and the release workflow now check that the version matches the VERSION file.

## 0.1.0-beta.6

Update by running `./install.sh` again, then **log out and back in once** so GNOME loads version 7 of the extension. Your `apps.json` is kept. New: Settings → Audio, Bluetooth keyboards and mice, per-app resolution, cinema mode, updates from Settings; robustness and security fixes from a code review; much less work in the background.

- **The gamepad service no longer keeps a CPU core busy during games.** Notices, Home Assistant and app events were checked after every batch of gamepad events (hundreds a second with a moving stick); now at most every 2 seconds.
- **A broken apps.json no longer stops the gamepad service.** A JSON error or a hand-edited entry (no "id", "extra_ids": null) used to crash it on the next shortcut. Events are handled one by one, entries are read tolerantly, and the service keeps the last good settings.
- **A broken apps.json no longer leaves a black screen.** Every save also keeps `apps.json.bak`; if apps.json can't be read, the launcher puts the last good copy back and keeps the broken one as `apps.json.broken`.
- **apps.json is readable only by you** (it can hold the Home Assistant token).
- **Updates are checked before they run.** Releases now come with a `SHA256SUMS`, and the launcher refuses a download that doesn't match it, or a release without one.
- **Updates, Flatpak updates and Bluetooth pairing can't run twice at once.** A second press used to start a second install that deleted the first one's files. Buttons under a "please wait" box can no longer be pressed.
- **Installing is atomic.** The installers copy next to the installed files and rename them into place, keeping the previous version as `.old`, so a failure or power cut mid-install never leaves the TV without launcher or gamepad service.
- **Forcing an app to close is safer.** SIGKILL is sent only if the process is still alive, through a pidfd (so a reused PID can never be hit), and `flatpak` calls have a timeout.
- **With Steam open, the volume no longer changes twice per press.** Steam Input's virtual gamepad copies every press; its events are now ignored.
- **No more freezes from a slow GNOME or a stuck media player.** The launcher asks for all open windows in one call instead of one per app, the "back to the launcher" shortcut runs off the gamepad thread, and media players get 0.5 s each.
- **The GNOME extension (version 7):** removes its pending timers when disabled; takes over its D-Bus name if something else holds it, and logs if it is lost; and limits notices (30 s at most, 4 on screen, 200 characters).
- **Releases run the tests first.** A new Tests workflow (on every push, and before every release) runs shellcheck, an extension syntax check, and both test suites. The release workflow checks the version against the VERSION file.
- **Smaller fixes.** The installer's "is the extension active" check no longer matches INACTIVE, the launcher's `.desktop` works with spaces in your home folder, pactl and wpctl output is read in the C locale, a failure to pause media no longer stops "back to the launcher", the service no longer restarts every 3 seconds when python3-evdev is missing (the log says what to install), and the launcher uses GLibUnix for its gamepad watches on GLib 2.80 and newer (no more deprecation warning in the log).
- **Less work in the background.**
  - The launcher stops reading the gamepads (it did so 60 times a second, all the time) and skips its network and gamepad checks while an app is in front. What was pressed inside the app is thrown away when the launcher comes back, so it doesn't act on it.
  - A stick only sends an event when it crosses the dead zone, instead of hundreds a second while it moves, and Steam Input's virtual gamepads are no longer opened at all.
  - The selected tile's glow breathes three times and then rests, instead of forever: the endless animation made GTK redraw the whole screen every frame while the launcher sat idle, keeping the GPU busy. Nothing on the launcher animates while an app is in front.
  - The service reads apps.json again only when it changes, and writes the TV-gate file only while the TV is off or when that changes (it was every 3 seconds, all day).
  - New gamepads are noticed the moment they appear (inotify on `/dev/input`), instead of within 2 seconds, and a gamepad that udev hadn't given access to yet on the first try is tried again as soon as it does. In front, the launcher sleeps until a gamepad has input instead of reading 60 times a second.
  - The internet status comes from NetworkManager's change signal instead of being asked every few seconds.
- **Under the hood:** one D-Bus client for every backend (the extension, MPRIS, Mutter, BlueZ, NetworkManager), so they all reconnect the same way, and a timeout no longer throws the connection away; one `Throttle` for the "at most every N seconds" checks; one helper for work off the screen's thread, which also keeps a second install, Flatpak update or pairing from starting, and Bluetooth listings from piling up. Unit tests with pytest in `tests/unit/` (`python3 -m pytest`), run in CI next to the end-to-end suites.

- **Settings → Audio:** pick where the sound goes (the TV, a soundbar, Bluetooth headphones or a speaker); what is playing moves along. It also pairs Bluetooth headphones and speakers. Uses PipeWire's `pw-dump` and `wpctl`, or `pactl` when installed.
- **Bluetooth pairing for keyboards and mice** too, next to gamepads (Settings → Gamepads → Pair a gamepad, keyboard or mouse), each marked with its kind.
- **Fixed: "Pair a gamepad" seemed to do nothing without a Bluetooth adapter.** Asking BlueZ, which isn't running without an adapter, waited about 8 seconds for it to start. The launcher now checks the kernel's adapters first and says at once that there is none, with "Checking Bluetooth…" on screen meanwhile.
- **The gamepad is never locked out by a wrong TV state.** If Home Assistant keeps saying the TV is off after 3 wake presses within a minute (it lost the TV, for example after the router gave the TV a new IP address), the gamepad stops being ignored for 10 minutes, or until Home Assistant sees the TV on again.
- **Per-app resolution.** In edit mode → Resolution, pick one of the screen's modes for an app (for example 4K for Jellyfin). The screen switches when the app opens or comes back, and returns to the default (GNOME's saved mode) in the launcher. The switch is never saved as GNOME's setting, so there is no "keep these settings?" prompt.
- **Cinema mode (Home Assistant).** With a second webhook set in Settings → Home Assistant → App and media events, the controller service sends app_opened / app_closed and media_playing / media_paused / media_stopped. `extras/home-assistant/cinema-mode.yaml` dims the lights while a video plays. A separate webhook, because a Home Assistant webhook only triggers one automation.
- **Updates from Settings.** A new Updates button: the newest launcher release from GitHub (downloaded, installed, and the launcher restarted), and the Flatpak apps (`flatpak update`).

## 0.1.0-beta.5

Update by running `./install.sh` again, then **log out and back in once** so GNOME loads version 6 of the extension (notices, the hidden pointer and the volume indicator need it). Your `apps.json` is kept. **The "back to the launcher" shortcut changed:** it is now Home + LB + RB instead of the guide button alone.

- **Documentation:** a full guide in [docs/](docs/README.md): installation, using the launcher, gamepads, configuration, Home Assistant, troubleshooting and development. The README is now a short overview.

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
