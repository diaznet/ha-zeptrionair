# ha-zeptrionair

Home Assistant custom integration (HACS) for **Feller zeptrionAir** WLAN devices. Local control and real-time push updates, with no cloud.

> 🚧 **Work in progress.** Not yet installable. See [PLAN.md](PLAN.md).

## Planned features

- Automatic discovery (mDNS and DHCP) or manual setup by hostname or IP.
- **Lights:** on/off, and dimmers (experimental).
- **Covers** (blinds, shades, awnings): open, close and stop, with live opening/closing state (including wall-switch presses) and optional position estimation from travel time.
- **Events** for wall keys and Smartbuttons, to use in automations.
- **Buttons** to recall scenes 1–4.
- Diagnostic sensors: Wi-Fi signal, and Smartfront temperature, light and humidity where available.
- Translated into English, Deutsch, Français and Italiano.

Built on the [zeptrionair-api](https://github.com/diaznet/zeptrionair-api) library.

## Disclaimer

Not affiliated with or endorsed by Feller AG or the Open Home Foundation. "zeptrion" and "zeptrionAIR" are trademarks of Feller AG.

## License

MIT
