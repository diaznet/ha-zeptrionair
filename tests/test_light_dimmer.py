"""Dimmer brightness (experimental timed dimming)."""

from __future__ import annotations

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_COLOR_MODE, ColorMode
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from .conftest import SERIAL, entity_id, wait_for_state


@pytest.fixture
def channels() -> list[FakeChannel]:
    return [FakeChannel("3", name="Dining dimmer", travel_time=5)]


@pytest.fixture
def btfu() -> str | None:
    return None


async def test_dimmer_brightness(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    dimmer = entity_id(hass, "light", f"{SERIAL}_ch1")
    assert hass.states.get(dimmer).state == STATE_OFF

    # Off -> "on" (100 %) -> dim down to about 40 %.
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: dimmer, ATTR_BRIGHTNESS: 102},
        blocking=True,
    )
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_ON)
    value = fake.channels[0].value
    assert 30 <= value <= 50
    state = hass.states.get(dimmer)
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.BRIGHTNESS
    assert state.attributes[ATTR_BRIGHTNESS] == round(value * 255 / 100)

    # Up to about 80 %.
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: dimmer, ATTR_BRIGHTNESS: 204},
        blocking=True,
    )
    assert 70 <= fake.channels[0].value <= 90
    requests = [body for method, _, body in fake.requests if method == "POST"]
    assert requests[0] == "cmd=on"
    assert requests[1].startswith("cmd=dim_down_")
    assert any(r.startswith("cmd=dim_up_") for r in requests[2:])

    # Plain turn_on on a dimmer just switches on.
    await hass.services.async_call("light", "turn_on", {ATTR_ENTITY_ID: dimmer}, blocking=True)
    assert fake.requests[-1][2] == "cmd=on"
