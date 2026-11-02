# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/diaznet/ha-zeptrionair/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/diaznet/ha-zeptrionair/releases/tag/v0.1.0
