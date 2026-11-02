"""Cover platform: commands, live movement state, position estimation."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverEntityFeature,
    CoverState,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_SUPPORTED_FEATURES
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeZeptrionDevice

from .conftest import SERIAL, entity_id, wait_for_state


def _cover(hass: HomeAssistant) -> str:
    return entity_id(hass, "cover", f"{SERIAL}_ch2")


def _service(hass: HomeAssistant, service: str, **data: object) -> object:
    return hass.services.async_call(
        "cover", service, {ATTR_ENTITY_ID: _cover(hass), **data}, blocking=True
    )


async def test_commands_and_movement_state(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    state = hass.states.get(_cover(hass))
    assert state.attributes["device_class"] == "shade"
    assert state.attributes[ATTR_SUPPORTED_FEATURES] == (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    assert state.attributes["assumed_state"] is True

    await _service(hass, "close_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSING)
    await _service(hass, "stop_cover")
    await wait_for_state(
        hass, _cover(hass), lambda s: s.state not in (CoverState.CLOSING, CoverState.OPENING)
    )
    await _service(hass, "open_cover")
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.OPENING)
    await wait_for_state(hass, _cover(hass), lambda s: s.state != CoverState.OPENING)
    posted = [body for method, _, body in fake.requests if method == "POST"]
    assert posted == ["cmd=close", "cmd=stop", "cmd=open"]


async def test_wall_keys_give_direction(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    await fake.press_key(8)  # btfu 4602: ch2 down
    await wait_for_state(hass, _cover(hass), lambda s: s.state == CoverState.CLOSING)
    await fake.press_key(7)  # opposite key while moving: stop
    await wait_for_state(hass, _cover(hass), lambda s: s.state != CoverState.CLOSING)


async def test_unknown_direction(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    # Something else (e.g. a Smartbutton elsewhere) starts the motor: running, direction unknown.
    await fake.set_value(2, 100)
    await hass.async_block_till_done()
    state = hass.states.get(_cover(hass))
    assert state.state not in (CoverState.OPENING, CoverState.CLOSING)
