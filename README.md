# Feller zeptrionAir for Home Assistant

[![Validate](https://github.com/diaznet/ha-zeptrionair/actions/workflows/validate.yml/badge.svg)](https://github.com/diaznet/ha-zeptrionair/actions/workflows/validate.yml)
[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://hacs.xyz/)

Custom integration for **Feller zeptrionAir** WLAN devices (zApp: 3340-2-x and 3340-4-x). It is fully local and uses push updates: wall-switch presses show up in Home Assistant within a fraction of a second, with no cloud and no polling every second.

<p align="center">
  <img src="img/zeptrionair-cover.jpg" alt="Feller zeptrionAir switch with Smartfront" width="300">
</p>

Built on the [zeptrionair-api](https://github.com/diaznet/zeptrionair-api) library.

## Features

| | |
|---|---|
| **Discovery** | Automatic via mDNS (`_zapp._tcp`, older firmware via `_http._tcp`) and DHCP, or manual setup by hostname/IP. A device's IP address is updated automatically when it changes. |
| **Lights** | On/off channels. Dimmers with brightness (**experimental**, untested on real dimmers; see below). |
| **Covers** | Blinds, shades and awnings: open, close and stop, with live *opening/closing* state, including when moved from the wall switch. **Open/closed** is detected from the end stops, without any setup. *Step up / Step down* buttons. Optional **position estimation** from travel times, with *set position*. |
| **Events** | One event entity per Smartfront key and Smartbutton (`press`/`release`), for automations. |
| **Scenes** | Buttons to recall and store the 4 scenes stored on each channel (disabled by default). |
| **Actions** | `zeptrionair.store_scene`, `recall_scene`, `move_step`, `write_name` (see below). |
| **Diagnostics** | Wi-Fi signal and device temperature sensors (disabled by default), plus a diagnostics download with identifying data redacted. |
| **Languages** | English, Deutsch, Français, Italiano |

Each zApp module becomes a device (Wi-Fi signal, keys, temperature). Each used channel becomes its own device named after the channel, with the light or cover as its main entity. The room stored on the zApp (`group`) is used as the suggested area.

## Installation

Requires Home Assistant **2025.2** or newer.

### Marketplace / HACS (recommended)
The integration is in the HACS default repositories, so you can install it by searching for it:

1. Open **Settings → Marketplace** (Home Assistant 2026.11 and newer) or **HACS** (older versions).
2. Search for **Feller zeptrionAir** and download it.
3. Restart Home Assistant.

If it doesn't show up in the search, add it as a custom repository instead: menu ⋮ → **Custom repositories**, add `https://github.com/diaznet/ha-zeptrionair` with type **Integration**, then continue with step 2.

### Manual
Copy `custom_components/zeptrionair` into your `config/custom_components/` folder and restart Home Assistant.

## Setup

Discovered devices appear under **Settings → Devices & services**. To add a device manually, click **Add integration → Feller zeptrionAir** and enter its hostname or IP address, e.g. `zapp-12345678` or `192.168.1.50`.

mDNS doesn't always work across Wi-Fi networks or VLANs, and some devices answer it poorly. If a device isn't discovered, add it manually. A DHCP reservation for each zApp is recommended.

### Options (per channel)
**Settings → Devices & services → Feller zeptrionAir → Configure**, then choose a channel:

- **Covers:** *Step duration* (ms, default 250) for the step buttons and action. *Estimate position*, plus *Travel time up/down* in seconds. Measure a full travel with a stopwatch. With estimation enabled, the position snaps to 0 % or 100 % whenever the cover reaches its end position. If the cover is moved by something the integration can't interpret (for example a Smartbutton on another device), the position becomes unknown until the next full open or close.
- **Dimmers:** *Full dimming time* (ms from 0 to 100 %, default 3400), used to reach a requested brightness.

## Actions

| Action | Targets | What it does |
|---|---|---|
| `zeptrionair.store_scene` | lights, covers | Stores the current state on the zApp as scene 1-4, like holding a scene key on the wall. For blinds, Feller recommends driving fully up first, then to the wanted height, then storing. |
| `zeptrionair.recall_scene` | lights, covers | Recalls scene 1-4. |
| `zeptrionair.move_step` | covers | Moves a cover `up` or `down` for `duration` ms (default: the *Step duration* option), e.g. to turn the slats of a blind. |
| `zeptrionair.write_name` | lights, covers | Writes a name and group (room) into the zApp, so the zeptrion app shows the same names. Without `name`/`group`, the device's name and area in Home Assistant are used. At most 32 bytes each. |

```yaml
action: zeptrionair.store_scene
target:
  entity_id: cover.office_shade
data:
  scene: 1
```

## How it works and its limits

- The devices report covers only as **motor running / stopped**, never a position. Direction comes from the command sent by Home Assistant, or from the wall key that was pressed (decoded from the Smartfront key layout).
- **Dimmers** are reported to answer *on* (100) at any brightness, so the brightness can't be read back. It is tracked **optimistically**: Home Assistant remembers the brightness it set (also across restarts and for scenes stored through Home Assistant). A brightness is reached by dimming for a computed time from the known brightness, or by switching on (100 %) and dimming down. Changes made at the wall are seen as on/off only. Feedback from dimmer owners is welcome.
- Home Assistant builds entity IDs from the area and the channel name, e.g. `cover.kitchen_kitchen_shade` for a channel named "Kitchen Shade" in the area "Kitchen". You can rename entity IDs in the entity settings.
- **End stops:** a run that nobody stopped (no stop command or key press, no step, no scene) ended at an end stop, because the zApp switches the motor off there. The cover then shows *closed* or *open*, also without position estimation. A run stopped in between shows *open*. A run of unknown direction (e.g. a Smartbutton on another zApp, or a scene) makes the state *unknown* until the next full run.

## Supported hardware

| | Status |
|---|---|
| 3340-2-B, firmware 01.08.28, on/off lights, blinds/shades, Smartfront | tested on real devices |
| 3340-2-A, 3340-4-A/B, dimmers, awnings, sensor fronts, firmware before 01.08 | expected to work, **untested** |

If you have untested hardware, please open an issue with a **diagnostics download** (device page → ⋮ → Download diagnostics), or with fixtures captured using [`zeptrion dump`](https://github.com/diaznet/zeptrionair-api#supported-hardware).

## Troubleshooting

- Enable debug logging:
  ```yaml
  logger:
    logs:
      custom_components.zeptrionair: debug
      zeptrionair_api: debug
  ```
- Entities become unavailable when the device has been unreachable for more than 60 seconds, and recover by themselves.
- Test a device outside Home Assistant: `pip install "zeptrionair-api[cli]"`, then `zeptrion info <host>` and `zeptrion watch <host>`.

## Development

Home Assistant's test tooling needs Linux and Python 3.14. On Windows, use WSL2 or a container, for example:

```bash
podman run --rm -it --network host -v "$PWD":/work -w /work python:3.14-slim bash
pip install uv && uv venv /venv && . /venv/bin/activate
uv pip install -r requirements_test.txt
pytest --cov                         # simulated devices, no hardware needed
python scripts/check_translations.py # en/de/fr/it completeness
```

The opt-in smoke test `tests/live/test_live.py` runs the integration against real devices (see its docstring). It never moves covers.

## Disclaimer

Not affiliated with or endorsed by Feller AG or the Open Home Foundation. "zeptrion" and "zeptrionAIR" are trademarks of Feller AG. Thanks to [heldchen/ha-zeptrion-air](https://github.com/heldchen/ha-zeptrion-air) (MIT), the first integration to use the device WebSocket.

## License

MIT
