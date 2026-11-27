# Troubleshooting

[← Documentation](README.md)

## Logs and checks

```bash
journalctl --user -fu htpc-controller             # the gamepad service: shortcuts, volume, notices, Home Assistant
journalctl --user -f -o cat /usr/bin/gnome-shell  # errors from the GNOME extension
gnome-extension/test.sh                           # open windows and the focused app
gnome-extension/test.sh launcher                  # bring the launcher to the front
gnome-extension/test.sh notify "Title" "text"     # show a test notice
gnome-extensions info htpc-launcher@htpc          # is the extension enabled and active? which version?
```

The launcher's own messages go to the session log, starting with `[launcher]`: `journalctl --user -f | grep '\[launcher\]'`.

## Common problems

**Apps don't open in full screen, the pointer doesn't hide, and notices or the volume indicator don't show up.**
GNOME is running an older version of the extension. After updating, **log out and back in** (or restart): GNOME only loads a new extension version at login. Check with `gnome-extensions info htpc-launcher@htpc`. The current version is 7.

**A shortcut does nothing.**
- Is the service running? Check with `systemctl --user status htpc-controller`.
- Does its log show the gamepad? Run `journalctl --user -u htpc-controller -n 30`.
- Is the TV off with the Home Assistant token set? The service then ignores every press except the one that wakes the TV. See [Home Assistant](home-assistant.md).
- Check the combos in Settings → Gamepads. **Restore the defaults** clears anything odd.

**Pressing Home throws me back to the launcher instead of opening Steam's menu.**
That was the behavior up to 0.1.0-beta.4. Since 0.1.0-beta.5 it takes Home + LB + RB. Update, and if you had turned off the guide button's Steam function in Steam's settings, turn it back on.

**The volume shortcut doesn't change the volume.**
It needs `wpctl` (PipeWire) or `pactl` (PulseAudio); the service's log says so if neither is found. It changes the **default** output, so check which one that is in GNOME's Settings → Sound.

**A gamepad does nothing in a Flatpak app.**
The app can't see input devices. Run `flatpak override --user --device=input <app id>`, or `--device=all` on Flatpak older than 1.15.6.

**X and Y seem swapped.**
The launcher recognizes Xbox drivers by driver or by name. If yours isn't recognized, please [open an issue](https://github.com/murilosalviati/htpc-launcher/issues) with the gamepad's name from `cat /proc/bus/input/devices`.

**Pair a gamepad says there's no adapter.**
- Check `bluetoothctl list`.
- A USB adapter may need its firmware. That's the `linux-firmware` package (named the same on Ubuntu, Debian, Fedora and Arch), usually installed already.
- Unblock the radio with `rfkill unblock bluetooth`.

**A gamepad won't pair.**
- Put it in pairing mode again; most leave it after about 30 seconds.
- Try once from GNOME's Settings → Bluetooth.
- Some gamepads need a firmware update from their maker.
- Forgetting the gamepad and pairing it again often helps.

**Everything feels slow on a 4K TV.**
Use a 60 Hz mode instead of 4K at 30 Hz. See [Installation → 4K TVs](installation.md#4k-tvs).

**The launcher came back with older settings.**
Your `apps.json` could not be read, probably because of a typo from editing it by hand. The launcher put back the last good copy (`apps.json.bak`) and kept the broken file as `~/.config/htpc-launcher/apps.json.broken`, so you can fix it and copy it back.

**An update was refused.**
The download didn't match the release's `SHA256SUMS`, or the release has none (releases older than this check). Try again later, or install by hand, as described in [Installation](installation.md#updating).

**The weather says the place was not found.**
For a Brazilian CEP, use 8 digits. For a city name, add the state or country, for example "Campinas SP".

**Home Assistant problems.**
See [Home Assistant → Troubleshooting](home-assistant.md#troubleshooting).

## Working over SSH

Commands over SSH don't reach the graphical session by default. Export these first:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
export WAYLAND_DISPLAY=wayland-0
```

To restart the launcher from SSH, start it through the systemd user manager. That way it gets the session's `DISPLAY` and `XAUTHORITY`, which X apps like Steam need:

```bash
pkill -f "[h]tpc-launcher/launcher.py"; sleep 1
systemd-run --user --collect -p KillMode=process gtk-launch htpc-launcher
```

Run these as a script (`bash restart.sh`), not inline in the `ssh` command line. Otherwise `pkill -f` can match the SSH session's own command and end it.

To restart the background service:

```bash
systemctl --user restart htpc-controller
```
