"""0.2: travel-time learning, calibration, slats, scene following, hold keys, LEDs,
Smartbutton programming, reconnect and connection statistics.

The fake shade (ch2) needs 2 s for a full travel (200 s x time_scale 0.01).
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverState,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api import ZeptrionDevice
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from custom_components.zeptrionair.const import (
    CONF_CHANNELS,
    CONF_POSITION_TRACKING,
    CONF_TILT_TIME,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DOMAIN,
)

from .conftest import SERIAL, entity_id, wait_for_state

TRAVEL = 2.0  # seconds, the fake shade's full travel


def _cover(hass: HomeAssistant) -> str:
    return entity_id(hass, "cover", f"{SERIAL}_ch2")


async def _call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


async def _cover_call(hass: HomeAssistant, service: str, **data: object) -> None:
    await _call(hass, "cover", service, entity_id=_cover(hass), **data)


async def _wait_still(hass: HomeAssistant, timeout: float = 8) -> None:
    await wait_for_state(
        hass,
        _cover(hass),
        lambda s: s.state not in (CoverState.OPENING, CoverState.CLOSING),
        timeout=timeout,
    )


def _channel_options(entry: MockConfigEntry) -> dict:
    return dict(entry.options.get(CONF_CHANNELS, {}).get("2", {}))


def _notification(hass: HomeAssistant) -> str:
    from homeassistant.components import persistent_notification

    notes = persistent_notification._async_get_or_create_notifications(hass)
    return " | ".join(n["message"] for n in notes.values())


# --- covers with travel times (position estimation)


@pytest.fixture
async def fake(
    hass: HomeAssistant, socket_enabled: None, channels: list[FakeChannel], btfu: str | None
):
    """Real-time fake: timed commands (move_close_<ms>) must match HA's clock here."""
    from homeassistant.config_entries import ConfigEntryState

    device = FakeZeptrionDevice(serial=SERIAL, channels=channels, btfu=btfu, time_scale=1)
    await device.start()
    yield device
    await hass.async_block_till_done()
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    await device.stop()


@pytest.fixture
def channels() -> list[FakeChannel]:
    return [
        FakeChannel("1", name="Terrace", group="Garden"),
        FakeChannel("5", name="Kitchen shade", group="Kitchen", travel_time=TRAVEL),
    ]


@pytest.fixture
def entry(fake: FakeZeptrionDevice) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_HOST: fake.host},
        options={
            CONF_CHANNELS: {
                "2": {
                    CONF_POSITION_TRACKING: True,
                    CONF_TRAVEL_TIME_UP: TRAVEL,
                    CONF_TRAVEL_TIME_DOWN: TRAVEL,
                    CONF_TILT_TIME: 0,
                }
            }
        },
    )


async def _to(hass: HomeAssistant, position: int) -> int:
    await _cover_call(hass, "set_cover_position", **{ATTR_POSITION: position})
    await asyncio.sleep(0.2)
    await _wait_still(hass)
    return hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION]


async def _known_position(hass: HomeAssistant) -> None:
    await _cover_call(hass, "close_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSED, timeout=8)
    await _cover_call(hass, "open_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.OPEN, timeout=8)
    await _wait_still(hass)


async def test_follows_a_scene_recalled_from_home_assistant(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    channel = fake.channels[1]
    await _known_position(hass)
    assert await _to(hass, 60) == pytest.approx(60, abs=6)
    await _call(hass, DOMAIN, "store_scene", entity_id=_cover(hass), scene=1)
    assert channel.cover_scenes[1][0] == "up"
    assert hass.states.get(_cover(hass)).attributes["scene_1"].startswith("up + ")

    await _cover_call(hass, "close_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSED, timeout=8)
    await _call(hass, DOMAIN, "recall_scene", entity_id=_cover(hass), scene=1)
    # two runs: up to the top, then 40 % down
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.OPENING)
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSING, timeout=8)
    await _wait_still(hass)
    shown = hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION]
    assert shown == pytest.approx(channel.position, abs=8)
    assert shown == pytest.approx(60, abs=8)


async def test_follows_a_scene_recalled_elsewhere(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    channel = fake.channels[1]
    await _known_position(hass)
    assert await _to(hass, 70) == pytest.approx(70, abs=6)
    await _call(hass, DOMAIN, "store_scene", entity_id=_cover(hass), scene=2)
    assert await _to(hass, 30) == pytest.approx(30, abs=6)
    # Another device recalls the scene: up to the top (recognised by its duration), then
    # down from the top (the only way it can go).
    async with ZeptrionDevice(fake.host) as other:
        await other.recall_scene(2, 2)
    # The first run has no direction hint: it is only recognised when it stops.
    for _ in range(100):
        if channel.value == 100:
            break
        await asyncio.sleep(0.03)
    assert channel.value == 100
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSING, timeout=8)
    await _wait_still(hass)
    shown = hass.states.get(_cover(hass)).attributes.get(ATTR_CURRENT_POSITION)
    assert shown == pytest.approx(channel.position, abs=10)


async def test_store_scene_from_the_bottom_drives_up_first(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    channel = fake.channels[1]
    await _cover_call(hass, "close_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSED, timeout=8)
    assert await _to(hass, 40) == pytest.approx(40, abs=6)  # came from the bottom
    await _call(hass, DOMAIN, "store_scene", entity_id=_cover(hass), scene=3)
    for _ in range(400):
        if "stored" in _notification(hass):
            break
        await asyncio.sleep(0.05)
    assert "Scene 3 stored" in _notification(hass)
    assert channel.cover_scenes[3][0] == "up"  # stored coming from the top
    assert channel.position == pytest.approx(40, abs=8)


async def test_hold_to_move_key(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    fake.hold_to_move = True
    await _known_position(hass)
    await fake.press_key(8, hold=0.5)  # held 0.5 s: moves while held
    await _wait_still(hass)
    state = hass.states.get(_cover(hass))
    assert state.state == CoverState.OPEN  # stopped by the release, not at the bottom
    assert 0 < state.attributes[ATTR_CURRENT_POSITION] < 100
