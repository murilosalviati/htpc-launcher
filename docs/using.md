# Using the launcher

[← Documentation](README.md)

## The home screen

![The home screen](preview.png)

The screen has up to three rows, top to bottom:

1. **Recently added:** the newest films and series on your Jellyfin server, once it's set up in Settings → Jellyfin. See [Recently added](#recently-added).
2. **The apps:** one tile per app.
3. **Home:** lights, switches and scenes from Home Assistant, once its address and token are set. Go down from the apps to reach it. See [Home](#home).

Without Jellyfin and Home Assistant, the apps sit alone in the middle of the screen.

### Tiles

The apps row has one tile per app. Move between them with the d-pad or the left stick, and press **Ⓐ** to open an app.

- **Selection:** the selected tile lifts and glows.
- **Opening:** pressing Ⓐ plays a short "button pressed" animation, and the tile pulses green while the app opens.
- **Already running:** a tile shows **open** under its name when the app is running. Selecting it brings back the existing window instead of starting a second copy.
- **Full screen:** apps open in full screen. Steam is the exception, because its Big Picture already is full screen.
- **Layout:** after 5 apps the grid wraps onto more rows.

### The top bar

- **Left:** the clock and the date, then the weather (an icon, the temperature and the place), once you set a location. At night the sun becomes a moon. It updates every 30 minutes.
- **Right**, from left to right:
  - **Gamepads:** an icon that lights up when a gamepad is connected (USB, Bluetooth or a wireless receiver). With more than one connected, it shows how many.
  - **Batteries:** one battery icon per wireless gamepad that reports its charge, from empty (red) to full, with a bolt while charging. A gamepad on a cable reports no charge, so no icon shows for it.
  - **Network:** a cable symbol on a wired connection, or Wi-Fi bars on Wi-Fi. Text appears only when the connection is limited or down.
  - **Settings** and **power:** two round buttons. Go up from the top row to reach them.

The power button opens a menu:

- **Turn off the TV**, when Home Assistant is set up. The TV turns off through Home Assistant, and the launcher goes back to its start (menus closed, the first app selected), ready for the next time. This option is selected when the menu opens.
- **Restart the computer** and **Shut down the computer**.
- **Cancel**, selected when there is no TV option. The menu is the confirmation: restart and shut down never start selected.

Everything around the edges keeps the same share of the screen on 1080p, 1440p or 4K. The icons are vectors, so they stay sharp.

### The footer

Reminders of the buttons and the current shortcuts.

**Ⓑ** goes back: it closes a menu or leaves edit mode.

### Recently added

The newest films and series on your Jellyfin server, newest first. The first one is wide, with its backdrop; new episodes of a series are grouped under the series, with how many are new.

- **Select one** to open the Jellyfin app, on its home screen, where the new items are at the top. Jellyfin must be one of your apps.
- **Updates:** the list is fetched when the launcher starts, then every 10 minutes while it's in front.
- **Setup:** Settings → **Jellyfin**: the address (such as `http://localhost:8096`), an API key (in Jellyfin: Dashboard → API Keys → +), and whose library to show. **Test** checks it. Typing the 32-character key with the gamepad is slow: you can also put it in `apps.json` (see [Configuration](configuration.md#jellyfin)).

If Jellyfin can't be reached, the row stays as it was, or hidden, and is tried again a minute later.

### Home

Go down from the apps to reach your lights. The apps dim and the screen scrolls.

- **Ⓐ** turns a light or switch on or off. The card changes at once; Home Assistant's own answer follows a moment later.
- **Ⓨ** on a dimmable light opens its brightness: **−** and **+** change it by 10%.
- **Scenes** sit in a row above the lights. Ⓐ runs one.
- **Which ones:** every light, by room, until you choose. Choose in Settings → Home Assistant → **Lights on the home screen**, which also lists switches. Without a choice, the first 6 scenes show.
- **Updates:** the states are read every 5 seconds while the launcher is in front.

It needs Home Assistant's address and access token. See the [Home Assistant guide](home-assistant.md#5-optional-lights-on-the-home-screen).

### No stray mouse pointer

Using the gamepad hides the mouse pointer on the whole screen, apps included. Moving the mouse brings it back.

## Notices

A short notice appears in the top-right corner for a few seconds when:

- a gamepad connects or disconnects;
- a gamepad's battery gets low (20%) or almost empty (10%);
- the internet drops, becomes limited, or comes back.

Notices show **over anything**, a full-screen video or game included. They don't take the focus or pause anything. Turn them off in Settings → On-screen notices.

## Settings

Select **Settings** (the gear) at the top right.

![Settings](settings.png)

| Row | What it does |
|---|---|
| **Apps** | Opens edit mode (below). |
| **Background** | Picks one of 9 dark themes: Midnight, Ocean, Forest, Aurora, Plum, Wine, Ember, Graphite or Black. Each one is previewed live as you move to it. |
| **Location** | The weather's place. Type a Brazilian CEP or a city name, then confirm the place it finds. Leave it empty to hide the weather. The data comes from [Open-Meteo](https://open-meteo.com/) and [ViaCEP](https://viacep.com.br/), which are free and need no account. |
| **Unit** | °C or °F. |
| **Language** | English or Brazilian Portuguese. It switches right away. |
| **On-screen notices** | Turns the notices on or off. |
| **Audio** | Where the sound goes: the TV, a soundbar, Bluetooth headphones or a speaker. Also pairs Bluetooth headphones and speakers. See [Audio](#audio). |
| **Gamepads** | Pair a gamepad, keyboard or mouse over Bluetooth, change the shortcuts, and see the volume shortcut. See [Gamepads](gamepads.md). |
| **Home Assistant** | The address, the webhook, the TV, the lights on the home screen and a connection test. See the [Home Assistant guide](home-assistant.md). |
| **Jellyfin** | The address, API key and user for the Recently added row, and a test. See [Recently added](#recently-added). |

At the bottom:

- **Updates** checks for a new launcher version and for Flatpak app updates. See [Updates](#updates).
- **Close the launcher** quits it. The "back to the launcher" shortcut opens it again.

### Edit mode (Settings → Apps)

- **Add an app:** pick it from the list of installed apps, Flatpaks included.
- **Edit an app:** change its name, its icon, the app it opens, or its resolution.
  - **Name:** typed on an on-screen keyboard. Ⓧ deletes, Ⓨ types a space, and a physical keyboard works too.
  - **Icon:** the app's own, or any image in `~/.local/share/htpc-launcher/app-icons/`.
  - **Resolution:** the default, or one of the screen's modes, as described in [Per-app resolution](#per-app-resolution).
- **Remove an app:** the grid reflows.

For the fields that aren't in edit mode, such as pause on Home, close commands and preferred windows, see [Configuration](configuration.md).

### Audio

Settings → **Audio** lists the sound outputs, with the one **In use** marked. Select another and all sound goes there, including whatever is already playing.

**Pair Bluetooth headphones or a speaker:**

1. Put the device in pairing mode, usually by holding its power or Bluetooth button until the light blinks.
2. Pick it from the list.
3. Once it is connected, it shows up as an output. Select it to send the sound there.

It uses PipeWire's own tools (`pw-dump` and `wpctl`, part of Ubuntu), or `pactl` when it is installed.

### Per-app resolution

Each app can use its own screen resolution. Set it in edit mode → **Resolution**. For example:

- **Jellyfin in 4K**, so movies use the full resolution, even at 30 Hz;
- **the launcher and Steam at 2560×1440 and 60 Hz**, so they feel smooth.

How it behaves:

- The screen switches when you open or come back to the app, and returns to the **default** when the launcher is in front. A TV usually goes black for a second or two while it switches.
- The default is the mode set in GNOME's Settings → Displays, kept in `~/.config/monitors.xml`.
- A switch is never saved as GNOME's setting. If anything goes wrong, a restart brings back the default.

### Updates

Settings → **Updates** shows the launcher's version and checks two things.

- **Launcher:** the newest release on GitHub.
  - If one is available, select it to download and install it. Your apps and settings are kept.
  - The launcher then offers to restart itself. When the GNOME extension changed too, it says so, and you need to restart the PC or log out and back in once.
- **Apps (Flatpak):** how many Flatpak apps have updates waiting. Select it to update them all.

## Steam

Steam opens in Big Picture. If it is already running in desktop mode, selecting its tile switches it to Big Picture. Its guide button opens Steam's own menu, and the launcher's shortcut is [Home + LB + RB](gamepads.md#shortcuts).
