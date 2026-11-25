# Configuration

[← Documentation](README.md)

Everything is in **`~/.config/htpc-launcher/apps.json`**. Most of it can be changed from the launcher's Settings. This page covers every field, for editing by hand.

- **Permissions:** the file is readable only by you, because it can hold a Home Assistant token.
- **Last good copy:** every save also writes `apps.json.bak`. If `apps.json` gets broken, the launcher restores that copy and keeps the broken file as `apps.json.broken`.

The launcher and the background service read the file again on their own, so most changes need no restart. Changes to the app list are the exception: they show up the next time the launcher starts. Back the file up before updating the launcher.

## Example

```json
{
  "language": "en",
  "background": "midnight",
  "temperature_unit": "celsius",
  "weather": {"query": "Lisboa", "name": "Lisbon, Portugal", "latitude": 38.72, "longitude": -9.14},
  "notifications": true,
  "shortcuts": {"home": ["guide", "l1", "r1"]},
  "launcher": {"launch": ["python3", "/home/me/.local/share/htpc-launcher/launcher.py"]},
  "apps": [
    {
      "name": "YouTube",
      "id": "rocks.shy.VacuumTube",
      "launch": ["flatpak", "run", "rocks.shy.VacuumTube", "--ozone-platform=wayland"],
      "pause_on_home": true
    },
    {
      "name": "Steam",
      "id": "com.valvesoftware.Steam",
      "extra_ids": ["steam"],
      "launch": ["flatpak", "run", "com.valvesoftware.Steam", "-gamepadui"],
      "on_resume": ["flatpak", "run", "com.valvesoftware.Steam", "steam://open/bigpicture"],
      "close": ["flatpak", "run", "com.valvesoftware.Steam", "-shutdown"],
      "close_timeout": 10,
      "fullscreen": false,
      "preferred_windows": ["Steam Big Picture Mode", "Steam"]
    }
  ]
}
```

## Apps

Each entry in `apps` is one tile.

| Field | What it does |
|---|---|
| `name` | The label under the tile. |
| `id` | The app's window name: its Flatpak id, `.desktop` id or WM_CLASS. `gnome-extension/test.sh` lists the names of every open window. |
| `extra_ids` | Other names for the same window. |
| `launch` | The command that starts the app, as a list. |
| `on_resume` | A command to run when the app is already running and you select it again, such as switching Steam to Big Picture. |
| `close` | The command that closes the app, for apps that only hide when their window closes. Steam uses `-shutdown`. |
| `close_timeout` | Seconds to wait before forcing the app to close. The default is 3. |
| `close_on_second_press` | The first close combo goes to the app itself (Moonlight uses it to end the stream). A second one within 15 seconds closes the app. |
| `pause_on_home` | Pause media (MPRIS) when you go back to the launcher from this app. |
| `fullscreen` | Put the app's windows in full screen when it opens. On by default; Steam defaults to off. |
| `display_mode` | The screen resolution for this app, such as `"3840x2160@30"` (the refresh rate is optional). The screen switches to it when the app opens or comes back, and returns to the default in the launcher. Set it in edit mode → Resolution. |
| `preferred_windows` | For apps with several windows: titles to bring to the front, in order of preference. Without it, the most recently used window comes up. |
| `icon` | A theme icon name or an image path. Without it, the launcher uses the icon the app installed. |
| `desktop` | The `.desktop` file to take the icon from, when it differs from `id`. |

## Top-level settings

| Field | Values | Default | In Settings |
|---|---|---|---|
| `language` | `en`, `pt-BR` | `en` | Language |
| `background` | `midnight`, `ocean`, `forest`, `aurora`, `plum`, `wine`, `ember`, `graphite`, `black` (see `htpc/themes.py`) | `midnight` | Background |
| `temperature_unit` | `celsius`, `fahrenheit` | `celsius` | Unit |
| `weather` | `{"query", "name", "latitude", "longitude"}`: the place you confirmed. Remove it to hide the weather. | none | Location |
| `notifications` | `true`, `false` | `true` | On-screen notices |
| `shortcuts` | `{"home": [...], "close": [...]}`: only the combos you changed. Button names: `guide`, `start`, `select`, `l1`, `r1`, `a`, `b`, `x`, `y`. Invalid combos fall back to the defaults. | Home + LB + RB, Start + Select + LB + RB | Gamepads |
| `home_assistant` | See the [Home Assistant settings reference](home-assistant.md#settings-reference). | none | Home Assistant |
| `jellyfin` | See [Jellyfin](#jellyfin) below. | none | Jellyfin |
| `tmdb` | `{"api_key": "..."}`, for Explore. See [Jellyfin](#jellyfin). | none | Jellyfin → Popular (TMDB) |
| `launcher.launch` | The command the service uses to start the launcher when it isn't running. `launcher/install.sh` fills it in. | | |

## Jellyfin

The `jellyfin` entry sets up the home screen's Recently added row:

```json
"jellyfin": {
  "url": "http://localhost:8096",
  "api_key": "0123456789abcdef0123456789abcdef",
  "user_id": "…",
  "user_name": "mu"
}
```

| Field | What it does | In Settings |
|---|---|---|
| `url` | Jellyfin's address. | Address |
| `api_key` | An API key, from Jellyfin's Dashboard → API Keys. | API key |
| `user_id`, `user_name` | Whose library and "latest" list to show. Without them, the first administrator. | User |
| `enabled` | `false` hides the row and keeps the rest. Defaults to `true`. | Films and series row |

For Explore, a `tmdb` entry with TMDB's short API key or its long API Read Access Token (Settings → Jellyfin → Popular (TMDB)):

```json
"tmdb": {"api_key": "0123456789abcdef0123456789abcdef"}
```

Older versions used Portuguese field names (`nome`, `abrir`...). They are converted automatically the first time the launcher starts.

## Other files

| Path | What it is |
|---|---|
| `~/.local/share/htpc-launcher/app-icons/` | Your own icons, picked in Settings → Apps. |
| `~/.local/share/htpc-launcher/tv-gate` | Whether the TV is off, written by the service for the launcher. See [Home Assistant](home-assistant.md). |
| `~/.local/share/htpc-launcher/tv-off` | When "Turn off TV" was last pressed. |
