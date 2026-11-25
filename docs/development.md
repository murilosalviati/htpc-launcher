# Development

[← Documentation](README.md)

## How it fits together

```
 ┌──────────────── GNOME Shell (Wayland) ───────────────┐
 │  htpc-launcher@htpc extension  ── D-Bus: org.htpc.Launcher
 │  (windows, full screen, notices, volume indicator, pointer)
 └──────────────────────▲───────────────────────────────┘
                        │ session bus
 ┌──────────────────────┴───────┐        ┌──────────────────────────┐
 │ launcher/ (GTK 4)            │        │ controller/ (systemd     │
 │ home screen, Settings,       │        │ user service)            │
 │ edit mode                    │        │ gamepad shortcuts,       │
 │                              │        │ volume, notices,         │
 │                              │        │ Home Assistant, TV state │
 └──────────────┬───────────────┘        └────────────┬─────────────┘
                └─────────── htpc/ (shared) ──────────┘
                      config, i18n, shortcuts, weather,
                      home_assistant, notifications
                      backends/ ── base.py (interface)
                                └─ linux/ (evdev, D-Bus, BlueZ, wpctl…)
```

On Wayland, a regular program can't raise another app's window or find out which window has focus. On Linux, a small GNOME Shell extension does that for the rest of the project.

## Folders

| Folder | What it is |
|---|---|
| `gnome-extension/` | The `htpc-launcher@htpc` GNOME Shell extension, with `install.sh` and a `test.sh` to call it by hand. |
| `controller/` | The background service (`controller.py`, `htpc-controller.service`): it reads the gamepads, runs the shortcuts and the volume, and drives the notices, Home Assistant and the TV-state gate. |
| `launcher/` | The home screen in GTK 4: `launcher.py` is the window, tiles, top bar and gamepad navigation, `settings.py` the Settings menus, `editor.py` edit mode and the on-screen keyboard. It also holds `launcher.css` and the vector `icons/`. |
| `htpc/` | The shared, OS-independent package (next table). |
| `htpc/backends/` | Everything that talks to the operating system, behind `base.py`. `linux/` implements it; `windows/` documents how a Windows port would work. |
| `extras/` | Files for other software: the Jellyfin gamepad map and the example Home Assistant automation. |
| `config/apps.json` | The default configuration. |
| `tests/` | Tests against a fake GNOME extension, a fake media player and a fake BlueZ. |
| `docs/` | This documentation. |

### `htpc/`

| Module | What it does |
|---|---|
| `config.py` | Reads and saves `apps.json`, and migrates old formats. |
| `paths.py` | File locations per OS. |
| `shortcuts.py` | The combos (defaults, validation, labels) and what each does: back to the launcher, close, volume. |
| `notifications.py` | Decides when to show a notice: gamepads, batteries, internet. |
| `home_assistant.py` | The webhook events, the TV state over the REST API, the gate that ignores input while the TV is off, and the app and media events (cinema mode). |
| `updates.py` | Checking and installing GitHub releases, and Flatpak updates. |
| `weather.py` | ViaCEP and Open-Meteo lookups. |
| `i18n.py` | On-screen text in English and Brazilian Portuguese. |
| `themes.py` | Background colors. |

## The GNOME extension's D-Bus API

The extension exports `org.htpc.Launcher` at `/org/htpc/Launcher` on the session bus. App ids are compared case-insensitively against each window's names (Flatpak id, `.desktop` id, WM_CLASS).

| Method | Since | What it does |
|---|---|---|
| `ListWindows() → s` | 1 | A JSON list of windows: `appId`, `ids`, `title`, `pid`, `focused`, `minimized`. |
| `IsRunning(s appId) → b` | 1 | Whether the app has a window. |
| `Activate(s appId) → b` | 1 | Raises the app's most recently used window. |
| `ActivatePreferring(s appId, as titles) → b` | 1 | Raises the first window whose title is in `titles`. |
| `FocusedApp() → s` | 1 | The focused app's id. |
| `Close(s appId) → u` | 1 | Closes the app's windows. Returns how many it closed. |
| `ShowLauncher() → b` | 1 | Brings the launcher to the front. |
| `FullscreenOnOpen(s appId, u seconds) → u` | 3 | Puts the app's windows in full screen as they open, for `seconds`. |
| `HidePointer() → b` | 4 | Hides the mouse pointer until the mouse moves. |
| `Notify(s title, s body, s iconPath, u seconds) → b` | 5 | Shows a notice in the top-right corner, over full-screen apps too. |
| `ShowOsd(s iconName, d level) → b` | 6 | Shows GNOME's level indicator (0..1), over full-screen apps too. |
| signal `FocusChanged(s appId)` | 1 | Emitted when the focused app changes. |

On top of full-screen apps, GNOME may hand the screen straight to the app ("unredirect"), which would hide anything drawn above it. While a notice or the volume indicator is up, the extension asks the compositor to keep compositing.

A new extension version is only loaded after logging out and back in. The Python side checks what's there and works with older versions, minus the newer features.

## Backends

`htpc/backends/base.py` defines what an OS must provide:

| Class | Provides |
|---|---|
| `WindowControl` | List, raise, close and full-screen windows; notices; the volume indicator; hiding the pointer; showing the launcher. |
| `Media` | Pausing whatever is playing (MPRIS on Linux). |
| `Gamepads` | Normalized button and stick events, the connected gamepads, and their batteries. |
| `AppCatalog` | Installed apps and their icons. |
| `System` | Starting and force-closing programs, restart and shut down, the connection type and connectivity, and the volume. |
| `Bluetooth` | Searching, pairing, trusting and forgetting devices. The default is "no Bluetooth". |
| `Display` | The screen's modes, the default mode, and switching modes for per-app resolutions. The default can't change modes. |

The Linux backend uses:

- **evdev** for gamepads, with Xbox X/Y fixed and virtual pads ignored;
- **jeepney** for D-Bus: the extension, MPRIS, NetworkManager and BlueZ;
- **Gio** for `.desktop` files;
- **systemd** for restart and shut down;
- **wpctl or pactl** for the volume;
- **Mutter's DisplayConfig** (D-Bus) for resolutions. Modes are applied "temporary", so there's no confirmation prompt and nothing is saved;
- **sysfs** for batteries.

### Porting to another OS

1. Implement the classes from `base.py` in `htpc/backends/<os>/`.
2. Add the OS to `get_backend()` in `htpc/backends/__init__.py`.

The launcher UI, Settings, the configuration and the shortcut rules then work unchanged. `htpc/backends/windows/__init__.py` describes how each piece would be done on Windows.

## Tests

```bash
dbus-run-session -- python3 tests/test_controller.py
xvfb-run -s "-screen 0 1920x1080x24" dbus-run-session -- python3 tests/test_launcher.py
```

- **`test_controller.py`:**
  - the shortcut rules and combos, and the volume, repeat included, with a fake `wpctl`;
  - Home Assistant events and the TV gate;
  - BlueZ pairing, against a fake `org.bluez`;
  - display modes, against a fake Mutter DisplayConfig;
  - app and media events;
  - update checks and installs, with a fake release archive;
  - the Linux backend's D-Bus and evdev handling;
  - config migration.
- **`test_launcher.py`:** drives the real UI with normalized gamepad events, on a virtual screen. It covers navigation, Settings and every submenu, edit mode, the on-screen keyboard, shortcut recording, pairing, Home Assistant, the resolution picker, updates and screen sizes. It explains the files it expects in `HOME` for the icon and app-list checks.

Both print `OK` or `FAILED` per check, and end with `ALL OK` or `SOME CHECKS FAILED`.

## Releases

Versions are `0.x` betas (`0.1.0-beta.5`, …), published as pre-releases. To make one:

1. Move the "Unreleased" section of `CHANGELOG.md` under the new version.
2. Update `VERSION` and `.github/release-notes.md`.
3. Push to `main`.
4. Run the **Release** workflow (Actions → Release → Run workflow) with the version.

The workflow tags `v<version>`, builds `htpc-launcher-<version>.tar.gz` and publishes the release.

## Contributing

Issues and pull requests are welcome. Keep the shared code free of OS calls (they go in a backend), add on-screen text in both languages in `i18n.py`, and run both test suites. Third-party logos are not part of the repository: screenshots use placeholder icons.

## License

GPL-3.0-or-later. See [LICENSE](../LICENSE).
