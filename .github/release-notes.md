> [!WARNING]
> **Beta, not a finished product.** This is an early version built and tested on one home setup. Expect rough edges: some features have only been tested against simulated hardware, and file formats or install steps may still change between versions. Back up `~/.config/htpc-launcher/apps.json` before updating, and please report problems in [Issues](https://github.com/murilosalviati/htpc-launcher/issues).

HTPC Launcher: a gamepad-driven TV home screen for Ubuntu with GNOME on Wayland.

![Launcher home screen](https://raw.githubusercontent.com/murilosalviati/htpc-launcher/main/docs/preview.png)

## What's new in 0.1.0-beta.6

### New in Settings
- **Audio:** pick where the sound goes: the TV, a soundbar, Bluetooth headphones or a speaker. What is playing moves along. Works with PipeWire (`wpctl`) or PulseAudio (`pactl`).
- **Bluetooth keyboards and mice** pair from the same list as gamepads, each marked with its kind. Without an adapter the screen says so at once, instead of seeming to do nothing.
- **Updates:** install the newest launcher release from GitHub and update the Flatpak apps, from the couch. Downloads are checked against the release's `SHA256SUMS` before anything is installed.
- **Per-app resolution:** in edit mode → Resolution, pick a screen mode for an app (4K for Jellyfin, for example). The screen switches when the app opens and goes back in the launcher, with no "keep these settings?" prompt.

### Home Assistant (optional)
- **Cinema mode:** with a second webhook, the gamepad service sends app opened / closed and media playing / paused / stopped. `extras/home-assistant/cinema-mode.yaml` dims the lights while a video plays.
- **The gamepad is never locked out by a wrong TV state.** If Home Assistant keeps saying the TV is off after 3 wake presses in a minute (after the router gave the TV a new IP address, for example), the gamepad stops being ignored for 10 minutes.

### Lighter and faster
- **Much less work in the background.** Behind an app, the launcher stops reading the gamepads entirely. In front, it sleeps until a gamepad has input instead of reading 60 times a second.
- **Lower idle GPU use.** The selected tile's glow breathes three times and rests, instead of making GTK redraw the whole screen every frame.
- **New gamepads show up instantly** (inotify on `/dev/input`), and the internet status comes from NetworkManager's change signal instead of being asked every few seconds.
- **The gamepad service no longer keeps a CPU core busy during games**, and Steam Input's virtual gamepads are ignored (with Steam open, the volume no longer changed twice per press).

### Sturdier
- **A broken apps.json no longer stops anything.** The launcher restores the last good copy (`apps.json.bak`) and keeps the broken one as `apps.json.broken`. apps.json is now readable only by you, since it can hold the Home Assistant token.
- **Installing is atomic:** a failure or power cut mid-install never leaves the TV without launcher or gamepad service.
- **Updates and pairing can't run twice at once**, and forcing an app to close can never hit the wrong process.
- **No more freezes** from a slow GNOME or a stuck media player.
- **GNOME extension version 7:** cleans up its timers, recovers its D-Bus name, and limits notices in time, count and length.

### For developers
- One D-Bus client for every backend, a shared `Throttle`, and a helper for background work.
- Unit tests with pytest in `tests/unit/`. Every push and every release runs them, together with shellcheck, an extension syntax check and both end-to-end suites.

The full list is in [CHANGELOG.md](https://github.com/murilosalviati/htpc-launcher/blob/main/CHANGELOG.md).

## Install or update

1. Download **htpc-launcher-0.1.0-beta.6.tar.gz** below and extract it: `tar xzf htpc-launcher-*.tar.gz`. `SHA256SUMS` lets you check it: `sha256sum -c SHA256SUMS`.
2. Run `./install.sh` inside the extracted folder. An existing `apps.json` is kept.
3. **Log out and back in.** This version updates the GNOME extension to version 7, and GNOME only loads it at login. On a first install, then run `gnome-extensions enable htpc-launcher@htpc`. The launcher starts by itself at login.

From this version on, later updates can also be installed from **Settings → Updates**.

Requirements:
- **System:** Ubuntu with GNOME on Wayland. It's tested on GNOME Shell 50.
- **Packages:** the installers add `python3-evdev`, `python3-jeepney`, `python3-gi` and `gir1.2-gtk-4.0` if they are missing.
- **Optional:**
  - a Bluetooth adapter, for pairing;
  - PipeWire or PulseAudio, for the volume shortcut and audio output;
  - Home Assistant, for TV control and cinema mode.

See the [documentation](https://github.com/murilosalviati/htpc-launcher/blob/main/docs/README.md) for everything else.
