"""0.2: travel-time learning, calibration, slats, scene following, hold keys, LEDs,
Smartbutton programming, reconnect and connection statistics.

The fake shade (ch2) needs 2 s for a full travel (200 s x time_scale 0.01).
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    CoverEntityFeature,
    CoverState,
)
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import (
    CONF_CHANNELS,
    CONF_LEARNED_DOWN,
    CONF_LEARNED_UP,
    CONF_POSITION_TRACKING,
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


async def test_learns_travel_times(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = _cover(hass)
    assert not hass.states.get(cover).attributes[ATTR_SUPPORTED_FEATURES] & (
        CoverEntityFeature.SET_POSITION
    )
    await _cover_call(hass, "close_cover")  # from the (unknown) top: nothing learned yet
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=8)
    assert CONF_LEARNED_DOWN not in _channel_options(loaded_entry)

    await _cover_call(hass, "open_cover")  # bottom -> top: travel time up
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.OPEN, timeout=8)
    await _cover_call(hass, "close_cover")  # top -> bottom: travel time down
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=8)
    options = _channel_options(loaded_entry)
    assert options[CONF_LEARNED_UP] and options[CONF_LEARNED_DOWN]
    assert options[CONF_TRAVEL_TIME_UP] == pytest.approx(TRAVEL, abs=0.5)
    assert options[CONF_TRAVEL_TIME_DOWN] == pytest.approx(TRAVEL, abs=0.5)
    # Both known: position estimation is on, without a reload.
    await hass.async_block_till_done()
    state = hass.states.get(cover)
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION
    assert state.attributes[ATTR_CURRENT_POSITION] == 0
    assert loaded_entry.state.name == "LOADED"


async def test_calibrate(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    await _call(hass, DOMAIN, "calibrate", entity_id=_cover(hass))
    for _ in range(400):
        if "calibrated" in _notification(hass):
            break
        await asyncio.sleep(0.05)
    assert "calibrated" in _notification(hass)
    options = _channel_options(loaded_entry)
    assert options[CONF_POSITION_TRACKING] is True
    assert options[CONF_TRAVEL_TIME_UP] == pytest.approx(TRAVEL, abs=0.5)
    posted = [b for m, _, b in fake.requests if m == "POST"]
    assert posted[:3] == ["cmd=open", "cmd=close", "cmd=open"]  # first open: already at top
    await hass.async_block_till_done()
    assert hass.states.get(_cover(hass)).attributes[ATTR_CURRENT_POSITION] == 100


async def test_calibrate_aborted(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    await _call(hass, DOMAIN, "calibrate", entity_id=_cover(hass))
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSING, timeout=8)
    with pytest.raises(Exception, match=r"."):
        await _call(hass, DOMAIN, "calibrate", entity_id=_cover(hass))  # busy / moving
    await _cover_call(hass, "stop_cover")
    for _ in range(200):
        if "interrupted" in _notification(hass):
            break
        await asyncio.sleep(0.05)
    assert "interrupted" in _notification(hass)
    assert CONF_LEARNED_DOWN not in _channel_options(loaded_entry)
