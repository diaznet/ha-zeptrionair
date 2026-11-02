"""Cover position estimation (runs in real time: 2 s travel)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from custom_components.zeptrionair.const import (
    CONF_CHANNELS,
    CONF_POSITION_TRACKING,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DOMAIN,
)

from .conftest import SERIAL, entity_id, wait_for_state


def _cover(hass: HomeAssistant) -> str:
    return entity_id(hass, "cover", f"{SERIAL}_ch2")


def _service(hass: HomeAssistant, service: str, **data: object) -> object:
    return hass.services.async_call(
        "cover", service, {ATTR_ENTITY_ID: _cover(hass), **data}, blocking=True
    )


@pytest.fixture
def channels() -> list[FakeChannel]:
    return [FakeChannel("1", name="Terrace"), FakeChannel("5", name="Kitchen shade", travel_time=2)]


@pytest.fixture
async def fake(
    hass: HomeAssistant, socket_enabled: None, channels: list[FakeChannel]
) -> AsyncIterator[FakeZeptrionDevice]:
    """Real-time fake (time_scale 1), so timed moves match the configured travel time."""
    device = FakeZeptrionDevice(serial=SERIAL, channels=channels, time_scale=1)
    await device.start()
    yield device
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
                    CONF_TRAVEL_TIME_UP: 2,
                    CONF_TRAVEL_TIME_DOWN: 2,
                }
            }
        },
    )


async def test_position_tracking(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    state = hass.states.get(_cover(hass))
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION
    assert ATTR_CURRENT_POSITION not in state.attributes  # unknown until a full travel

    with pytest.raises(HomeAssistantError, match="position is unknown"):
        await _service(hass, "set_cover_position", **{ATTR_POSITION: 50})

    await _service(hass, "set_cover_position", **{ATTR_POSITION: 0})  # = close fully
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSED, timeout=8)
    assert hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION] == 0

    await _service(hass, "open_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.OPEN, timeout=8)
    assert hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION] == 100
    assert hass.states.get(_cover(hass)).attributes["current_position"] == 100

    await _service(hass, "set_cover_position", **{ATTR_POSITION: 50})
    assert fake.requests[-1][2].startswith("cmd=move_close_")
    await wait_for_state(
        hass,
        _cover(hass),
        lambda s: (
            s.state == CoverState.OPEN
            and s.attributes.get(ATTR_CURRENT_POSITION) not in (None, 100)
        ),
        timeout=8,
    )
    position = hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION]
    assert 30 <= position <= 70
