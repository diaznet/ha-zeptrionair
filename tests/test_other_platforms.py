"""Event, button and sensor platforms, diagnostics."""

from __future__ import annotations

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN

from .conftest import SERIAL, wait_for_state


async def test_key_events(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    entities = er.async_get(hass)
    key5 = entities.async_get_entity_id("event", DOMAIN, f"{SERIAL}_key_5")
    smart3 = entities.async_get_entity_id("event", DOMAIN, f"{SERIAL}_key_3")
    assert key5 == f"event.zapp_{SERIAL}_key_5"
    assert smart3 == f"event.zapp_{SERIAL}_smartbutton_3"
    assert entities.async_get_entity_id("event", DOMAIN, f"{SERIAL}_key_1") is None  # unused

    await fake.press_key(3)
    await wait_for_state(hass, smart3, lambda s: s.attributes.get("event_type") == "release")
    state = hass.states.get(smart3)
    assert state.attributes["function"] == "smartbutton"

    await fake.press_key(5)
    await wait_for_state(hass, key5, lambda s: s.attributes.get("event_type") == "release")
    state = hass.states.get(key5)
    assert state.attributes["function"] == "channel"
    assert state.attributes["channels"] == [1]
    assert state.attributes["direction"] == "up"
    assert state.attributes["code"] == "8501"


async def _enable(hass: HomeAssistant, entry: MockConfigEntry, entity_id: str) -> None:
    er.async_get(hass).async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_scene_buttons(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    entities = er.async_get(hass)
    button = entities.async_get_entity_id("button", DOMAIN, f"{SERIAL}_ch2_scene_2")
    assert button is not None
    assert button.endswith("recall_scene_2")
    assert entities.async_get(button).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await _enable(hass, loaded_entry, button)
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)
    assert fake.requests[-1] == ("POST", "/zrap/chctrl/ch2", "cmd=recall_s2")


async def test_sensors(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    entities = er.async_get(hass)
    rssi = entities.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_rssi")
    temperature = entities.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_device_temperature")
    assert rssi == f"sensor.zapp_{SERIAL}_wi_fi_signal"
    assert temperature == f"sensor.zapp_{SERIAL}_device_temperature"
    # lux/humidity are "none" on the fake front: no entities
    assert entities.async_get_entity_id("sensor", DOMAIN, f"{SERIAL}_illuminance") is None

    await _enable(hass, loaded_entry, rssi)
    await _enable(hass, loaded_entry, temperature)
    assert hass.states.get(rssi).state == "-60"
    assert float(hass.states.get(temperature).state) == 24.5


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    loaded_entry: MockConfigEntry,
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    assert result["entry"]["data"]["host"] == "**REDACTED**"
    assert result["device"]["serial"] == "**REDACTED**"
    assert result["mac"] == "**REDACTED**"
    assert result["channels"][0]["name"] == "**REDACTED**"
    assert result["channels"][0]["category"] == 1
    assert result["capabilities"]["websocket"] is True
    assert result["smartfront"]["keys"][4]["channels"] == [1]
    assert result["state"]["values"] == {"1": 0, "2": 0}
    assert SERIAL not in str(result)
