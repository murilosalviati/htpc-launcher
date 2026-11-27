# Installation

[← Documentation](README.md)

## Requirements

- **A Linux distribution with GNOME on Wayland**, GNOME Shell 46 to 51. It is used every day on Ubuntu with GNOME 50. The installer is tested on each release with these distributions' packages:

  | Distribution | Package manager |
  |---|---|
  | Ubuntu 24.04 and later, Debian 13 | apt |
  | Fedora Workstation | dnf |
  | Arch Linux (with GNOME) | pacman |
  | openSUSE Tumbleweed (with GNOME) | zypper |

  GNOME 46 (Ubuntu 24.04) should work but hasn't been tried on a real screen yet. Other desktops (KDE Plasma, SteamOS's game mode) are not supported: the launcher relies on its GNOME extension to bring apps forward, close them and draw over them.
- **Python 3 with GTK 4, python-evdev and jeepney.** The installers add whichever are missing with your distribution's package manager, which asks for your password once.
  - **Immutable systems** (Fedora Silverblue, Bazzite and the like) can't install packages that way: the installer stops and says what to add with `rpm-ostree install`, then restart and run it again.
- **The apps you want on the home screen.** The default configuration expects these Flatpaks, and you can change them later from Settings → Apps:
  - `rocks.shy.VacuumTube`: YouTube's TV interface.
  - `org.jellyfin.JellyfinDesktop`
  - `com.moonlight_stream.Moonlight`
  - `com.valvesoftware.Steam`
- **Optional:**
  - A Bluetooth adapter, to pair wireless gamepads from the launcher.
  - PipeWire (`wpctl`, the default on current distributions) or PulseAudio (`pactl`), for the volume shortcut.
  - [Home Assistant](home-assistant.md), for TV control.

## Install

1. Download the newest `htpc-launcher-<version>.tar.gz` from the [Releases page](https://github.com/murilosalviati/htpc-launcher/releases). The betas are marked as pre-releases.
2. Extract it and run the installer:

   ```bash
   tar xzf htpc-launcher-*.tar.gz
   cd htpc-launcher-*/
   ./install.sh
   ```

3. **Log out and back in**, so GNOME loads the extension.
4. On a first install, enable the extension:

   ```bash
   gnome-extensions enable htpc-launcher@htpc
   ```

The launcher starts by itself at every login from then on. To start it right away, run `gtk-launch htpc-launcher`.

### What gets installed

| Part | Where | What it is |
|---|---|---|
| GNOME extension | `~/.local/share/gnome-shell/extensions/htpc-launcher@htpc/` | Lets the launcher control windows on Wayland and draws the notices and the volume indicator. |
| Controller service | `htpc-controller.service` (systemd, user) | Reads the gamepads in the background and runs the shortcuts inside any app. |
| Launcher | `~/.local/share/htpc-launcher/` and `~/.local/share/applications/htpc-launcher.desktop` | The home screen. Starts at login through `~/.config/autostart/`. |
| Configuration | `~/.config/htpc-launcher/apps.json` | Your apps and settings. An existing file is **never** overwritten. |

To install the parts one at a time, install them in this order:

```bash
gnome-extension/install.sh   # then log out and back in, and: gnome-extensions enable htpc-launcher@htpc
controller/install.sh
launcher/install.sh
```

## Updating

The easy way is from the couch: **Settings → Updates → Launcher** downloads and installs the newest release, then restarts the launcher. See [Using the launcher → Updates](using.md#updates).

By hand: download the new version and run `./install.sh` again. Your `apps.json` is kept either way.

When a release says the **GNOME extension changed**, log out and back in once after updating. GNOME only loads a new extension version at login. The release notes and the [CHANGELOG](../CHANGELOG.md) say when the extension changed. The current version is 7.

> With auto-login, logging out may not log you back in. Restarting the machine always works. `sudo systemctl restart gdm` also works, but it closes every open app.

## App notes

### Jellyfin Desktop

`launcher/install.sh` makes three changes for Jellyfin's Flatpak:

- **Gamepad access:** the Flatpak can't see gamepads by default, so the installer gives it access to input devices (`flatpak override --user --device=input`, or `--device=all` on Flatpak older than 1.15.6).
- **Xbox gamepad map:** Jellyfin's own Xbox map only matches controllers named "Xbox One". The installer adds `extras/jellyfin/xbox-series.json` to each Jellyfin profile. This map matches any Xbox controller and leaves the guide button alone. The profiles only exist after Jellyfin's first start, so **run `launcher/install.sh` again after opening Jellyfin once**.
- **TV mode:** you switch this yourself, so the interface is made for a gamepad. In Jellyfin, go to Settings → Client settings → layout, or set `"layout": "tv"` in its `jellyfin-desktop.conf`.

### Steam

- **Big Picture:** Steam opens in Big Picture (`-gamepadui`). If Steam is already running in desktop mode, selecting its tile switches it to Big Picture.
- **Guide button:** Steam keeps it. Pressing it alone opens Steam's menu, and the launcher only reacts to Home + LB + RB. Some of Steam's own guide-button chords may overlap that, for example Guide + RB takes a screenshot. If one gets in the way, [pick another combo](gamepads.md#changing-the-shortcuts).

### Other Flatpak apps

Many Flatpaks can't see gamepads. Give one access with:

```bash
flatpak override --user --device=input <app id>
```

On Flatpak older than 1.15.6, use `--device=all` instead.

### Your own icons

Put PNG files in `~/.local/share/htpc-launcher/app-icons/` and pick them in Settings → Apps. If they are in an `app-icons/` folder at the root of the extracted package, `launcher/install.sh` copies them there for you.

## 4K TVs

Many integrated GPUs only drive 4K at 30 Hz, and big-screen interfaces like Steam's Big Picture feel sluggish at 30 frames per second. A 60 Hz mode such as 2560×1440 or 1920×1080 is much smoother, and the TV scales it up. The launcher adapts to the new size by itself. Pick the mode in GNOME's Settings → Displays.

## Uninstalling

```bash
systemctl --user disable --now htpc-controller.service
rm ~/.config/systemd/user/htpc-controller.service
gnome-extensions uninstall htpc-launcher@htpc
rm ~/.config/autostart/htpc-launcher.desktop ~/.local/share/applications/htpc-launcher.desktop
rm -r ~/.local/share/htpc-launcher          # the launcher and your icons
rm -r ~/.config/htpc-launcher               # your apps.json; keep it if you may come back
```
