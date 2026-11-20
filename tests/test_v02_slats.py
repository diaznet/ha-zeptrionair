"""0.2: travel-time learning, calibration, slats, scene following, hold keys, LEDs,
Smartbutton programming, reconnect and connection statistics.

The fake shade (ch2) needs 2 s for a full travel (200 s x time_scale 0.01).
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.const import ATTR_SUPPORTED_FEATURES, CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
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


@pytest.fixture
def channels() -> list[FakeChannel]:
    return [
        FakeChannel("1", name="Terrace", group="Garden"),
        FakeChannel("5", name="Kitchen shade", group="Kitchen", travel_time=TRAVEL, tilt_time=1),
    ]


async def test_slats(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    hass.config_entries.async_update_entry(
        loaded_entry,
        options={CONF_CHANNELS: {"2": {**_channel_options(loaded_entry), CONF_TILT_TIME: 1.0}}},
    )
    await hass.async_block_till_done()
    cover = _cover(hass)
    features = hass.states.get(cover).attributes[ATTR_SUPPORTED_FEATURES]
    assert features & CoverEntityFeature.SET_TILT_POSITION
    await _known_position(hass)
    assert hass.states.get(cover).attributes[ATTR_CURRENT_TILT_POSITION] == 100

    await _cover_call(hass, "close_cover_tilt")
    assert fake.requests[-1][2] == "cmd=move_close_1000"
    await asyncio.sleep(0.2)
    await _wait_still(hass)
    state = hass.states.get(cover)
    assert state.attributes[ATTR_CURRENT_TILT_POSITION] == 0
    assert state.attributes[ATTR_CURRENT_POSITION] == 100  # only the slats turned
    assert fake.channels[1].tilt == pytest.approx(0, abs=5)
    assert fake.channels[1].position == pytest.approx(100, abs=2)

    await _cover_call(hass, "set_cover_tilt_position", tilt_position=50)
    command = fake.requests[-1][2]
    assert command.startswith("cmd=move_open_")
    assert int(command.rsplit("_", 1)[1]) == pytest.approx(500, abs=20)
