"""0.1.3: end stops without travel times, steps, scenes, write name, action errors."""

from __future__ import annotations

import pytest
from homeassistant.components.cover import CoverState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN
from custom_components.zeptrionair.entity import truncate_utf8

from .conftest import SERIAL, entity_id, wait_for_state

MOVING = (CoverState.OPENING, CoverState.CLOSING)


def _posted(fake: FakeZeptrionDevice) -> list[str]:
    return [body for method, _, body in fake.requests if method == "POST"]


async def _cover_service(hass: HomeAssistant, cover: str, service: str) -> None:
    await hass.services.async_call("cover", service, {ATTR_ENTITY_ID: cover}, blocking=True)


async def test_end_stops_without_travel_times(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    assert hass.states.get(cover).state == "unknown"

    # A run nobody stopped ended at the end stop.
    await _cover_service(hass, cover, "close_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=5)
    await _cover_service(hass, cover, "open_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.OPEN, timeout=5)

    # Stopped half way: open (not at the bottom).
    await _cover_service(hass, cover, "close_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSING)
    await _cover_service(hass, cover, "stop_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.OPEN)
    assert 0 < fake.channels[1].position < 100


async def test_end_stops_from_wall_keys(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    await fake.press_key(8)  # ch2 down, runs to the end stop
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=5)

    await fake.press_key(7)  # ch2 up
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.OPENING)
    await fake.press_key(8)  # opposite key while running: stop
    await wait_for_state(hass, cover, lambda s: s.state not in MOVING)
    assert hass.states.get(cover).state == CoverState.OPEN
    assert 0 < fake.channels[1].position < 100


async def test_unknown_run_makes_state_unknown(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    await _cover_service(hass, cover, "close_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=5)
    await fake.set_value(2, 100)  # started by something we can't interpret
    await fake.set_value(2, 0)
    await wait_for_state(hass, cover, lambda s: s.state == "unknown")


async def test_steps(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    step_down = entity_id(hass, "button", f"{SERIAL}_ch2_step_down")
    step_up = entity_id(hass, "button", f"{SERIAL}_ch2_step_up")
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: step_down}, blocking=True)
    assert _posted(fake)[-1] == "cmd=move_close_250"
    # A timed run ends by itself without reaching the end stop: open, not closed.
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.OPEN, timeout=5)

    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: step_up}, blocking=True)
    assert _posted(fake)[-1] == "cmd=move_open_250"

    await hass.services.async_call(
        DOMAIN,
        "move_step",
        {ATTR_ENTITY_ID: cover, "direction": "down", "duration": 1500},
        blocking=True,
    )
    assert _posted(fake)[-1] == "cmd=move_close_1500"


async def test_cover_scenes(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    store = entity_id(hass, "button", f"{SERIAL}_ch2_store_3")
    registry = er.async_get(hass)
    assert registry.async_get(store).entity_category == "config"
    assert registry.async_get(store).disabled_by is er.RegistryEntryDisabler.INTEGRATION

    await hass.services.async_call(
        DOMAIN, "store_scene", {ATTR_ENTITY_ID: cover, "scene": 3}, blocking=True
    )
    assert _posted(fake)[-1] == "cmd=store_s3"
    await _cover_service(hass, cover, "close_cover")
    await wait_for_state(hass, cover, lambda s: s.state == CoverState.CLOSED, timeout=5)
    await hass.services.async_call(
        DOMAIN, "recall_scene", {ATTR_ENTITY_ID: cover, "scene": 3}, blocking=True
    )
    assert _posted(fake)[-1] == "cmd=recall_s3"
    # The scene run's direction and end are unknown to us: no false open/closed.
    await wait_for_state(hass, cover, lambda s: s.state == "unknown", timeout=5)


async def test_store_button(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    store = entity_id(hass, "button", f"{SERIAL}_ch1_store_1")
    er.async_get(hass).async_update_entity(store, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: store}, blocking=True)
    assert fake.requests[-1] == ("POST", "/zrap/chctrl/ch1", "cmd=store_s1")


async def test_write_name(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    # Explicit name and group.
    await hass.services.async_call(
        DOMAIN,
        "write_name",
        {ATTR_ENTITY_ID: light, "name": "Küche Decke", "group": "EG"},
        blocking=True,
    )
    assert (fake.channels[0].name, fake.channels[0].group) == ("Küche Decke", "EG")
    assert loaded_entry.runtime_data.channels[0].name == "Küche Decke"

    # Defaults: the device name in HA and its area.
    devices = dr.async_get(hass)
    device = next(
        d
        for d in dr.async_entries_for_config_entry(devices, loaded_entry.entry_id)
        if (DOMAIN, f"{SERIAL}_ch1") in d.identifiers
    )
    area = ar.async_get(hass).async_get_or_create("Terrasse")
    devices.async_update_device(device.id, name_by_user="Outdoor lamp", area_id=area.id)
    await hass.services.async_call(DOMAIN, "write_name", {ATTR_ENTITY_ID: light}, blocking=True)
    assert (fake.channels[0].name, fake.channels[0].group) == ("Outdoor lamp", "Terrasse")


def test_truncate_utf8() -> None:
    assert truncate_utf8("  short  ") == "short"
    long = "ä" * 20  # 40 bytes
    cut = truncate_utf8(long)
    assert len(cut.encode()) <= 32
    assert cut == "ä" * 16


async def test_action_without_matching_target(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    with pytest.raises(ServiceValidationError):  # move_step only applies to covers
        await hass.services.async_call(
            DOMAIN, "move_step", {ATTR_ENTITY_ID: light, "direction": "up"}, blocking=True
        )
