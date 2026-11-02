"""Options flow."""

from __future__ import annotations

import pytest
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import ATTR_SUPPORTED_FEATURES, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from custom_components.zeptrionair.const import (
    CONF_CHANNELS,
    CONF_DIM_TIME,
    CONF_POSITION_TRACKING,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DOMAIN,
)
from tests.conftest import SERIAL as fake_serial
from tests.conftest import entity_id


@pytest.fixture
def channels() -> list[FakeChannel]:
    return [
        FakeChannel("1", name="Lamp"),
        FakeChannel("5", name="Shade"),
        FakeChannel("3", name="Dimmer"),
    ]


async def test_cover_options(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"channel": "2"})
    assert result["step_id"] == "cover"
    assert result["description_placeholders"] == {"channel": "Shade (ch2)"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_POSITION_TRACKING: True, CONF_TRAVEL_TIME_UP: 25, CONF_TRAVEL_TIME_DOWN: 22.5},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_CHANNELS]["2"] == {
        CONF_POSITION_TRACKING: True,
        CONF_TRAVEL_TIME_UP: 25,
        CONF_TRAVEL_TIME_DOWN: 22.5,
    }
    await hass.async_block_till_done()  # reload
    state = hass.states.get(entity_id(hass, "cover", f"{fake_serial}_ch2"))
    assert state.attributes[ATTR_SUPPORTED_FEATURES] & CoverEntityFeature.SET_POSITION


async def test_dimmer_options(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"channel": "3"})
    assert result["step_id"] == "dimmer"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DIM_TIME: 8000}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded_entry.options[CONF_CHANNELS]["3"] == {CONF_DIM_TIME: 8000}
    await hass.async_block_till_done()


async def test_nothing_to_configure(hass: HomeAssistant, socket_enabled: None) -> None:
    async with FakeZeptrionDevice(channels=[FakeChannel("1")]) as fake:
        entry = MockConfigEntry(domain=DOMAIN, unique_id=fake.serial, data={CONF_HOST: fake.host})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "nothing_to_configure"
        await hass.config_entries.async_unload(entry.entry_id)


async def test_options_need_loaded_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="1", data={CONF_HOST: "x"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
