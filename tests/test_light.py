"""Light platform."""

from __future__ import annotations

import pytest
from homeassistant.components.light import ATTR_COLOR_MODE, ColorMode
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeZeptrionDevice

from .conftest import SERIAL, entity_id, wait_for_state


async def test_on_off(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    terrace = entity_id(hass, "light", f"{SERIAL}_ch1")
    state = hass.states.get(terrace)
    assert state.state == STATE_OFF

    await hass.services.async_call("light", "turn_on", {ATTR_ENTITY_ID: terrace}, blocking=True)
    assert fake.channels[0].value == 100
    await wait_for_state(hass, terrace, lambda s: s.state == STATE_ON)
    assert hass.states.get(terrace).attributes[ATTR_COLOR_MODE] == ColorMode.ONOFF

    await hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: terrace}, blocking=True)
    await wait_for_state(hass, terrace, lambda s: s.state == STATE_OFF)


async def test_wall_switch_updates_state(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    terrace = entity_id(hass, "light", f"{SERIAL}_ch1")
    await fake.press_key(5)  # btfu 8501: ch1 on
    await wait_for_state(hass, terrace, lambda s: s.state == STATE_ON)
    await fake.press_key(6)
    await wait_for_state(hass, terrace, lambda s: s.state == STATE_OFF)


async def test_command_failure(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    terrace = entity_id(hass, "light", f"{SERIAL}_ch1")
    fake.fail_next = [400]
    with pytest.raises(HomeAssistantError, match="did not accept"):
        await hass.services.async_call("light", "turn_on", {ATTR_ENTITY_ID: terrace}, blocking=True)
