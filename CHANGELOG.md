# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1]

### Fixed
- Saving a cover's settings with *Estimate position* left at its default (off) no longer stops learning from switching estimation on once both travel times are known. Switching it off after that is still kept.

### Changed
- The user documentation moved to the [wiki](https://github.com/diaznet/ha-zeptrionair/wiki), in English, German, French and Italian.

## [0.2.0]

### Added
- **Travel times without a stopwatch:** a *Calibrate* button and `zeptrionair.calibrate` action (fully up, down, up, then back; result as a notification), and a *Learn travel times* option (on by default) that updates them from every full run between the end stops. Position estimation turns on once both are known. Verified on real hardware.
- **Slats:** *Slat tilt time* option; blinds with it get tilt open/close/stop/set position. Verified on real hardware.
- **Scene recalls are followed:** scenes stored through Home Assistant are remembered (`scene_N` attribute) and their two-run replay is tracked exactly; recalls from elsewhere are recognised by the duration of their first run. Storing a scene on a blind that came from the bottom first drives it up and back, as Feller recommends. Verified on real hardware.
- A cover at an end stop can only move away from it: runs of unknown origin starting there keep a direction.
- Wall keys that move a cover only while held: the release counts as a stop.
- **Smartbutton programming:** `zeptrionair.program_smartbutton` with commands for lights and covers of any zApp and raw Feller requests; the 730-byte limit is checked before anything blinks.
- **Smartfront LEDs:** a light entity per used key's LED background colour (disabled by default), and *Undo LED change*.
- *Reconnect* button, and *Connections* / *Short outages* / *Long outages* diagnostic sensors.

### Changed
- Changing options no longer reloads the integration; they apply immediately.
- The cover's `current_position` attribute is Home Assistant's own (integer) again; the exact position is kept in the restore data.
- Requires `zeptrionair-api` 0.2.0.

### Fixed
- A temporary error reading the Wi-Fi signal or the sensors (the zApp sometimes answers HTTP 500 during a motor run) no longer makes the whole update or the setup fail.

## [0.1.3]

### Fixed
- **Dimmers**: dimmers are reported to answer `100` at any lit brightness. Brightness is now tracked optimistically (remembered across restarts) instead of being read back, and reached by dimming for a computed time from the known brightness (no flash to 100 % when the light is already on). Default full dimming time 3400 ms.
- A direction learned from a command or key press could be reused by an unrelated run within 3 s.

### Added
- Covers show **open/closed** from the end stops, without travel times: a run nobody stopped ended at an end stop. Verified on real hardware.
- *Store scene 1-4* buttons (configuration, disabled by default) for lights and covers.
- *Step up* / *Step down* buttons for covers, with a per-cover *Step duration* option (default 250 ms).
- Actions `zeptrionair.store_scene`, `zeptrionair.recall_scene`, `zeptrionair.move_step` and `zeptrionair.write_name` (writes the Home Assistant name and area into the zApp).
- Dimmer scenes stored through Home Assistant remember their brightness.

### Changed
- Requires `zeptrionair-api` 0.1.1.

## [0.1.2]

### Changed
- README: installation now leads with searching in the Marketplace/HACS (the integration is in the HACS default repositories); custom repository steps kept as a fallback.
- README: cropped the cover picture.
- New brand icon, drawn after the real zeptrionAIR switch with Smartfront (frame, top key with LEDs, up/down keys).
- `manifest.json`: added integration categories `plugs_switches` and `blinds_curtains`, used by the Marketplace catalog.
- CI: lint uses the ruff version pinned in `requirements_test.txt`; release workflow uses `action-gh-release` 3.0.4.

## [0.1.1]

### Changed
- `hacs.json`: set `country` to Switzerland and Liechtenstein (zeptrionAIR is sold there only), as required for the HACS default repositories.
- README: cover picture; removed the migration section.

## [0.1.0]

### Added
- Config flow:
  - manual host;
  - mDNS discovery (`_zapp._tcp`, plus `_http._tcp` filtered to `zapp-*`);
  - DHCP discovery, including IP updates for registered devices;
  - reconfigure flow.
- Push updates through the device WebSocket, with `chnotify` fallback and safety polling. Entities become unavailable after 60 s without connection.
- Lights: on/off, and dimmers with brightness (experimental).
- Covers:
  - open/close/stop;
  - live opening/closing state, including wall-switch presses;
  - optional position estimation from travel times, with set position.
- Event entities for Smartfront keys and Smartbuttons.
- Scene recall buttons (disabled by default).
- Diagnostic sensors: Wi-Fi signal and device temperature (disabled by default).
- Diagnostics download with identifying data redacted.
- Per-channel options: cover travel times and position estimation, dimmer timing.
- Translations: English, German, French, Italian.
- Local brand icon (Home Assistant 2026.3+).

[Unreleased]: https://github.com/diaznet/ha-zeptrionair/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/diaznet/ha-zeptrionair/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/diaznet/ha-zeptrionair/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/diaznet/ha-zeptrionair/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/diaznet/ha-zeptrionair/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/diaznet/ha-zeptrionair/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/diaznet/ha-zeptrionair/releases/tag/v0.1.0
