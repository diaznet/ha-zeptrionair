# AGENTS.md: ha-zeptrionair

Home Assistant custom integration `zeptrionair` for Feller zeptrionAir zApps. All device I/O goes through the [`zeptrionair-api`](https://github.com/diaznet/zeptrionair-api) library (sibling repo `../zeptrionair-api`); protocol facts live in its `docs/protocol.md`.

## Where things are

- `custom_components/zeptrionair/coordinator.py`: one coordinator per zApp. It holds the push connection, direction hints from commands and key presses, connection statistics, and the LED colours.
- `cover.py`: all cover logic. That covers end-stop detection, position estimation, learned and calibrated travel times, slats, following scene recalls, and sequences such as calibration and storing a scene from the top. The device only reports *motor running/stopped*; every other state is inferred here.
- `services.py`: actions, registered in `async_setup`, which resolve their targets through `hass.data[DOMAIN]`.
- `tests/`: they run against the library's `FakeZeptrionDevice`. The `tests/test_v02_*` scene and slat modules use a real-time fake, so timed commands match HA's clock. `tests/live/test_live.py` holds opt-in hardware tests; its docstring has the env vars.

## Commands

HA's test tooling needs Linux and Python 3.14. On this Windows machine, use the podman container `zha-test` (repo mounted at `/work/ha-zeptrionair`):

```powershell
podman machine start; podman start zha-test
podman exec -w /work/ha-zeptrionair zha-test sh -c '. /venv/bin/activate && ruff check . --fix -q; ruff format .; python -m pytest -q -p no:cacheprovider --cov'
podman run --rm --network host -v C:\Dev\zeptrionair\ha-zeptrionair:/github/workspace:Z ghcr.io/home-assistant/hassfest
```

CI (`.github/workflows/validate.yml`) also runs `scripts/check_translations.py` and `scripts/check_versions.py`. Run those before pushing.

The shell tool rejects long inline scripts. Write a Python script to a scratch directory outside the repo and run it there.

## Writing code

- Before writing code against an HA or library API, look it up with Context7 (`npx ctx7@latest library …`, then `docs …`). HA APIs change between versions. Support stays at the minimum version in `hacs.json` (2025.2); check signatures at runtime where they differ, as `services.py` does for `async_extract_entity_ids`.
- Every user-facing string goes into `translations/en.json` and into `de.json`, `fr.json` and `it.json`. German is **Swiss High German**: "ss" instead of "ß", and "Store/Storen" for covers.
- Add a test with every behaviour change. Timing-sensitive cover tests must pass 3 runs in a row.

## Documentation

User documentation is the **GitHub wiki**, in English, German (de-CH), French and Italian. The README stays short: what the integration is, a quick install, and links into the wiki.

- Clone it next to this repo: `git clone https://github.com/diaznet/ha-zeptrionair.wiki.git ../ha-zeptrionair.wiki`.
- `scripts/check_wiki.py` holds the page list (`_NAMES`), with each page's file name per language. Add new pages there. `python scripts/check_wiki.py ../ha-zeptrionair.wiki --fix` writes the language switchers, `_Sidebar.md` and `_Footer.md`, then checks completeness, links, anchors and identifiers. Set `WIKI_FORBIDDEN` to a regex of your real hostnames so they are caught too.
- Any change to a feature, option, action or default updates the matching wiki page **in all four languages** in the same piece of work. Labels quote the exact strings from `translations/*.json`.
- Push the wiki only after the checker prints `OK`.

## Releasing

1. If the library changed, release it first (see its AGENTS.md). Then pin the exact version in `manifest.json` and `requirements_test.txt`.
2. Bump `version` in `manifest.json` and move `[Unreleased]` in `CHANGELOG.md` to the new version, with compare links.
3. Push `main` and wait for Validate to go green.
4. Tag `vX.Y.Z` (annotated) and push the tag. The Release workflow builds `zeptrionair.zip`, and `check_versions.py` must agree with the tag. Then check that the release asset's manifest has the new version.

## Guardrails

- Committed files (code, tests, docs, wiki, commit messages) use example identifiers only: `192.168.1.50`, `zapp-12345678`, `cover.office_shade`. Pass real IPs to live tests through env vars.
- Credit third-party projects only where the README already does. A fact known only from an unconfirmed third-party source is written as **[UNVERIFIED]**, without attribution.
- Hardware: only move covers the user has approved, only in daylight, and tell the user before each run. Leave them fully open afterwards. Programming a Smartbutton erases its old programme, so only program the one the user names.
- The user has allowed commits, pushes and tags. A tag needs green CI on its commit.
