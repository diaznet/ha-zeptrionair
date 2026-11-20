"""Dimmers: optimistic brightness (the zApp reports 100 at any lit level), timed dimming."""

from __future__ import annotations

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_COLOR_MODE, ColorMode
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from .conftest import SERIAL, entity_id, wait_for_state


@pytest.fixture
def channels() -> list[FakeChannel]:
    # travel_time = full dim time of the fake (3.4 s, like the integration's default)
    return [FakeChannel("3", name="Dining dimmer", travel_time=3.4)]


@pytest.fixture
def btfu() -> str | None:
    return None


def _posted(fake: FakeZeptrionDevice) -> list[str]:
    return [body for method, _, body in fake.requests if method == "POST"]


async def _turn_on(hass: HomeAssistant, dimmer: str, **data: object) -> None:
    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: dimmer, **data}, blocking=True
    )


async def test_dimmer_brightness(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    dimmer = entity_id(hass, "light", f"{SERIAL}_ch1")
    channel = fake.channels[0]
    assert hass.states.get(dimmer).state == STATE_OFF

    # Off -> "on" (100 %) -> dim down by 60 % of the full time.
    await _turn_on(hass, dimmer, **{ATTR_BRIGHTNESS: 102})
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_ON)
    assert _posted(fake) == ["cmd=on", "cmd=dim_down_2040"]
    state = hass.states.get(dimmer)
    assert state.attributes[ATTR_COLOR_MODE] == ColorMode.BRIGHTNESS
    assert state.attributes[ATTR_BRIGHTNESS] == 102  # optimistic, the zApp only says "100"
    await wait_for_state(hass, dimmer, lambda s: True)
    assert channel.value == 100

    # Already on: dim up from the known brightness, no flash to 100 %.
    await _turn_on(hass, dimmer, **{ATTR_BRIGHTNESS: 204})
    assert _posted(fake)[-1] == "cmd=dim_up_1360"
    assert hass.states.get(dimmer).attributes[ATTR_BRIGHTNESS] == 204

    # A tiny change below the minimum timed command is only remembered.
    count = len(_posted(fake))
    await _turn_on(hass, dimmer, **{ATTR_BRIGHTNESS: 205})
    assert len(_posted(fake)) == count
    assert hass.states.get(dimmer).attributes[ATTR_BRIGHTNESS] == 205

    # Plain turn_on: "on" means 100 %.
    await _turn_on(hass, dimmer)
    assert _posted(fake)[-1] == "cmd=on"
    assert hass.states.get(dimmer).attributes[ATTR_BRIGHTNESS] == 255

    # The wall: on/off are pushed; the level of a dimmer isn't (it stays the last known one).
    await hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: dimmer}, blocking=True)
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_OFF)
    assert hass.states.get(dimmer).attributes.get(ATTR_BRIGHTNESS) is None


async def test_dimmer_scenes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    dimmer = entity_id(hass, "light", f"{SERIAL}_ch1")
    await _turn_on(hass, dimmer, **{ATTR_BRIGHTNESS: 128})
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_ON)
    await hass.services.async_call(
        "zeptrionair", "store_scene", {ATTR_ENTITY_ID: dimmer, "scene": 2}, blocking=True
    )
    assert _posted(fake)[-1] == "cmd=store_s2"
    assert hass.states.get(dimmer).attributes["scene_2_brightness"] == 128

    await _turn_on(hass, dimmer)  # 100 %
    await hass.services.async_call(
        "zeptrionair", "recall_scene", {ATTR_ENTITY_ID: dimmer, "scene": 2}, blocking=True
    )
    assert _posted(fake)[-1] == "cmd=recall_s2"
    await hass.async_block_till_done()
    assert hass.states.get(dimmer).attributes[ATTR_BRIGHTNESS] == 128


@pytest.fixture
def entry(fake: FakeZeptrionDevice, hass: HomeAssistant) -> MockConfigEntry:
    from homeassistant.const import CONF_HOST

    from custom_components.zeptrionair.const import DOMAIN

    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("light.dining_dimmer", STATE_ON),
                {"brightness": 77, "scenes": {"1": 200}},
            )
        ],
    )
    return MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: fake.host})


async def test_brightness_restored(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    dimmer = entity_id(hass, "light", f"{SERIAL}_ch1")
    assert dimmer == "light.dining_dimmer"
    await fake.set_level(1, 30)  # lit at some level -> reports 100
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_ON)
    state = hass.states.get(dimmer)
    assert state.attributes[ATTR_BRIGHTNESS] == 77
    assert state.attributes["scene_1_brightness"] == 200


@pytest.mark.parametrize("reported", [40])
async def test_reported_level_is_used(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice, reported: int
) -> None:
    dimmer = entity_id(hass, "light", f"{SERIAL}_ch1")
    fake.dimmer_reports_level = True
    await fake.set_level(1, reported)
    await wait_for_state(hass, dimmer, lambda s: s.state == STATE_ON)
    assert hass.states.get(dimmer).attributes[ATTR_BRIGHTNESS] == round(reported * 255 / 100)
