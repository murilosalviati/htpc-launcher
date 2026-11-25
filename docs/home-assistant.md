# Home Assistant

The launcher can work with [Home Assistant](https://www.home-assistant.io/) to control the TV:

- **Wake the TV with the gamepad.** Plug in a gamepad, turn one on, or press any button. If the TV is off, Home Assistant turns it on and switches it to the HTPC's input.
- **Turn the TV off from the launcher.** A "Turn off TV" button in the middle of the footer.
- **Ignore the gamepad while the TV is off.** The launcher and the gamepad shortcuts do nothing while the screen is dark. The first press only wakes the TV, so you never open an app you can't see.
- **Lights on the home screen.** Lights, switches and scenes under the apps: turn them on and off, and dim them, with the gamepad.
- **Cinema mode.** The launcher tells Home Assistant when an app opens or closes and when a video plays, pauses or stops, so an automation can dim the lights.

All of this is optional. Without Home Assistant the launcher works exactly as before.

[← Documentation](README.md)

## Contents

- [How it works](#how-it-works)
- [What you need](#what-you-need)
- [Setup](#setup)
  - [1. The automation in Home Assistant](#1-the-automation-in-home-assistant)
  - [2. The launcher's settings](#2-the-launchers-settings)
  - [3. Optional: ignore the gamepad while the TV is off](#3-optional-ignore-the-gamepad-while-the-tv-is-off)
  - [4. Optional: cinema mode](#4-optional-cinema-mode)
  - [5. Optional: lights on the home screen](#5-optional-lights-on-the-home-screen)
- [Using it](#using-it)
- [Settings reference](#settings-reference)
- [Events](#events)
- [Troubleshooting](#troubleshooting)
- [Security](#security)

## How it works

```
gamepad ──► controller service ──webhook──► Home Assistant automation ──► TV
                 │      ▲                       (turn on / input / turn off)
                 │      └──── TV state (REST API, with a token) ◄──┘
                 ▼
             launcher  ──webhook ("tv_off")──► Home Assistant
```

- **Webhook:** the controller service (`htpc-controller`) and the launcher send short events to a Home Assistant **webhook**. One automation in Home Assistant reacts to them. A webhook on the local network needs no password or token.
- **TV state:** to know whether the TV is on, the controller service also needs a **long-lived access token**. With it, it asks Home Assistant for the TV's state every 3 seconds.
- **Configuration:** everything lives in the `home_assistant` entry of `~/.config/htpc-launcher/apps.json`, and most of it can be set from Settings → Home Assistant.

## What you need

- Home Assistant on the same local network as the HTPC.
- The TV in Home Assistant as a `media_player` entity, with `media_player.turn_on`, `turn_off` and `select_source` working.
  - **LG webOS:** the [LG webOS TV integration](https://www.home-assistant.io/integrations/webostv/) can't turn the TV on by itself. Add the usual automation that sends Wake-on-LAN when Home Assistant asks for it: a `webostv.turn_on` trigger, then the `wake_on_lan.send_magic_packet` action with the TV's MAC address. Also turn on "LG Connect Apps" / "Turn on via Wi-Fi" (the name varies by model) on the TV.
  - **Other brands:** these work too, as long as those three actions work for them.
- The name of the input the HTPC is plugged into, **exactly as Home Assistant lists it** in the TV's `source_list` attribute. Renamed inputs keep their new name, for example `PC` instead of `HDMI 3`. Check it under Developer tools → States → your TV.

## Setup

### 1. The automation in Home Assistant

1. Copy [`extras/home-assistant/wake-tv.yaml`](../extras/home-assistant/wake-tv.yaml).
2. Replace the placeholders:

   | Placeholder | Replace with |
   |---|---|
   | `WEBHOOK_ID` | Any hard-to-guess text, such as `htpc-gamepad-` followed by random letters and numbers. It goes in the launcher too. |
   | `media_player.tv` | Your TV's entity. |
   | `"HDMI 3"` | The HTPC's input, exactly as in `source_list`. |

3. In Home Assistant, go to Settings → Automations & scenes → Create automation → ⋮ → Edit in YAML, paste it and save.

What the automation does:

| Event | Action |
|---|---|
| `tv_off` | Turns the TV off. |
| any other (`gamepad_activity`, `gamepad_connected`, `test`) | If the TV is off, turns it on and waits for it. Then, if it isn't on the HTPC's input, switches to it. |

The automation runs in `queued` mode, so the events of the "Turn off TV" press are handled in order. It also ignores gamepad activity for 15 seconds after the TV goes off, so that pressing Ⓐ on "Turn off TV" doesn't immediately turn the TV back on.

### 2. The launcher's settings

On the HTPC, open Settings (the gear at the top right) → **Home Assistant**:

1. **Address:** type Home Assistant's address, such as `http://192.168.0.22:8123`.
   - The on-screen keyboard gets an extra `: / _` row here.
   - An IP address is more reliable than `homeassistant.local`.
2. **Webhook ID:** type the same `WEBHOOK_ID` you used in the automation.
3. **Test the connection:** sends a `test` event. In Home Assistant, the automation's trace should show a new run.

From now on, the gamepad wakes the TV. Changes apply right away, with nothing to restart.

To show the **"Turn off TV" button** in the footer, switch it on in the same menu.

### 3. Optional: ignore the gamepad while the TV is off

This step needs a long-lived access token:

1. **Create the token:** in Home Assistant, click your profile (bottom left) → **Security** → **Long-lived access tokens** → **Create token**. Name it `htpc-launcher` and copy it. Home Assistant only shows it once.
2. **Add it to `apps.json`:** the token is too long to type with a gamepad. Add it on the HTPC, inside the `home_assistant` entry:

   ```json
   "home_assistant": {
     "url": "http://192.168.0.22:8123",
     "webhook_id": "htpc-gamepad-…",
     "token": "eyJhbGciOi…"
   }
   ```

3. **Pick the TV:** in Settings → Home Assistant → **TV**, the launcher lists Home Assistant's media players. Pick yours.
4. **Check it:** **Test the connection** now also says whether the TV is on or off.

### 4. Optional: cinema mode

App and media events go to a **second webhook**. A Home Assistant webhook only triggers one automation, and the one that wakes the TV must not react to these events.

1. **Copy the automation:** start from [`extras/home-assistant/cinema-mode.yaml`](../extras/home-assistant/cinema-mode.yaml). It dims the lights to 10% while a video plays in Jellyfin or YouTube, to 50% on pause, and back to 100% when the video stops or the app closes. Lights that are off stay off.
2. **Fill it in:** replace `WEBHOOK_ID` with a new hard-to-guess id. Replace `light.living_room` with your lights (a light group or scenes work too), and set the app names to match your `apps.json`.
3. **Connect the launcher:** in Settings → Home Assistant → **App and media events**, type the same id. Leave it empty to send nothing.

The events, with what they carry, are listed under [Events](#events). Adapt the automation to anything else: a soundbar's sound mode, blinds, or pausing a robot vacuum.

### 5. Optional: lights on the home screen

With the address and the [access token](#3-optional-ignore-the-gamepad-while-the-tv-is-off), the launcher shows a **Home** row under the apps: go down from the apps to reach it. No automation is needed; the launcher calls Home Assistant's API directly.

- **What shows:** every light, grouped by room (Home Assistant's areas), plus up to 6 scenes.
- **Choose:** Settings → Home Assistant → **Lights on the home screen** lists every light and switch (also fans and input booleans). Tick the ones you want; they show in the order you ticked them. **All lights** goes back to the default. **Show under the apps** turns the row off.
- **Use it:** Ⓐ turns a light or switch on or off, or runs a scene. Ⓨ on a dimmable light sets its brightness.

The token needs no extra permission, but rooms come from a template call: a token of a non-admin user still works, without the room names.

## Using it

**Wake the TV:**
- Press any button or plug in a gamepad. The TV turns on and switches to the HTPC.
- A connected gamepad sends button presses at most once a minute, so Home Assistant isn't flooded. The exception is right after "Turn off TV": then the next press is sent at once.

**Turn the TV off:** select **Turn off TV** in the footer and press Ⓐ. Wait about 15 seconds before pressing a button to wake it again.

**TV off, with the token set:**
- The launcher and the gamepad shortcuts (back to the launcher, close the app) ignore the gamepad.
- The first press only wakes the TV. If it's still off 8 seconds later, the next press asks again.
- The gamepad works normally again once Home Assistant reports the TV as on.
- If Home Assistant can't be reached, or the TV's state is unknown (`unavailable`), nothing is blocked. The launcher never gets stuck because of Home Assistant.
- If Home Assistant still says the TV is off after 3 wake presses within a minute, it has probably lost the TV (for example, the TV got a new IP address after a router restart). The gamepad then works normally for 10 minutes, or until Home Assistant sees the TV on again. Give the TV a fixed IP address in your router to avoid this.

> Apps that read the gamepad themselves (Steam, Jellyfin, Moonlight) still receive it while the TV is off. Only the launcher and the shortcuts are blocked.

## Settings reference

The `home_assistant` entry of `apps.json`:

| Field | What it does | In Settings |
|---|---|---|
| `url` | Home Assistant's address. | Address |
| `webhook_id` | The automation's webhook id. | Webhook ID |
| `enabled` | `false` turns the whole integration off and keeps the other fields. Defaults to `true`. | Use Home Assistant |
| `events_webhook_id` | A second webhook, for app and media events (cinema mode). Empty: nothing is sent. | App and media events |
| `token` | A long-lived access token, used to read the TV's state. | Access token (shows only whether it is set) |
| `tv_entity` | The TV's entity, such as `media_player.living_room_tv`. | TV |
| `tv_name` | The TV's name as shown in Settings. Filled in when you pick the TV. | TV |
| `home_screen` | `false` hides the lights under the apps. Defaults to `true`. | Lights on the home screen → Show under the apps |
| `devices` | The lights and switches under the apps, in order (entity ids). Without it, every light, by room. | Lights on the home screen |
| `scenes` | The scenes or scripts above them (entity ids). Without it, the first 6 scenes. | (apps.json only) |

At the top level of `apps.json`, `tv_off_button` (`true`/`false`, default `false`) shows or hides the "Turn off TV" button. In Settings it's **"Turn off TV" button**.

## Events

Each event is a `POST` to `<url>/api/webhook/<webhook_id>` with a JSON body:

```json
{"event": "gamepad_activity", "gamepad": "Xbox Series X Controller", "host": "htpc"}
```

| `event` | Sent by | When |
|---|---|---|
| `gamepad_connected` | controller service | A gamepad shows up (plugged in, or turned on). |
| `gamepad_activity` | controller service | A button is pressed: at most once a minute, right away after "Turn off TV", and on every wake press while the TV is off. |
| `tv_off` | launcher | The "Turn off TV" button. |
| `test` | launcher | Settings → Home Assistant → Test the connection. |

On the **events webhook** (`events_webhook_id`), only if it is set, the controller service checks every 2 seconds and sends:

```json
{"event": "media_playing", "app": "Jellyfin", "front": "Jellyfin", "host": "htpc"}
```

| `event` | When | `app` |
|---|---|---|
| `app_opened` | An app from `apps.json` opens its first window. | That app's name. |
| `app_closed` | Its last window closes. | That app's name. |
| `media_playing` | Something starts playing (any media player, through MPRIS). | The app in front. |
| `media_paused` | Everything that was playing is paused. | The app in front. |
| `media_stopped` | Nothing is playing or paused any more. | The app in front. |

`front` is always the app in front, or `launcher`. Nothing is sent for what was already open or playing when the service started.

In an automation, the body is in `trigger.json`, so you can write your own automations around any of these events.

## Troubleshooting

```bash
journalctl --user -fu htpc-controller   # events sent, "tv: on" / "tv: off", errors
cat ~/.local/share/htpc-launcher/tv-gate  # {"blocked": true} while the TV is off
```

**The TV doesn't turn on:**
- In Home Assistant, open the automation's **Traces**. Is there a new run when you press a button?
  - **No run:** check the address and the webhook ID with **Test the connection**.
  - **A run that stops at "turn on":** the TV can't be woken. Check the Wake-on-LAN automation and the TV's "turn on via network" option.

**The TV turns on but stays on another input:** the `htpc_input` in the automation doesn't match `source_list` exactly. Check capitals and renamed inputs.

**The gamepad is still blocked after the TV turned on:**
- The TV entity may be reporting `off` while the picture is on. Compare with Developer tools → States.
- The block lifts within 3 seconds of Home Assistant reporting it as on.

**The gamepad isn't blocked while the TV is off:**
- The token and the TV must both be set. Check **Test the connection**: it should say the TV is off.
- Some TVs report `unavailable` for a few seconds while turning off. That state never blocks.

**"Turn off TV" turns the TV off and right back on:** the automation is missing the 15-second guard. Update it from the current `wake-tv.yaml`.

## Security

- **Webhooks:** they accept calls from the local network only (`local_only: true` in the automation), without a token. Anyone on your network who knows the webhook ID can turn the TV on or off, so use a hard-to-guess ID.
- **The token:** it gives full access to Home Assistant, as your user. It's stored in plain text in `~/.config/htpc-launcher/apps.json`, so treat that file like a password. If it leaks, delete the token in Home Assistant (Profile → Security) and create a new one.
