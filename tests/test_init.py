"""Setup, devices, unload, availability."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN

from .conftest import SERIAL, entity_id, wait_for_state


async def test_setup_creates_devices_and_entities(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED
    devices = {
        next(iter(d.identifiers))[1]: d
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), loaded_entry.entry_id)
    }
    hub = devices.get(SERIAL)
    assert hub is not None
    assert hub.model == "3340-2-B"
    assert hub.manufacturer == "Feller"
    assert hub.name == f"zApp-{SERIAL}"
    assert hub.sw_version.startswith("01.08.28")
    assert (dr.CONNECTION_NETWORK_MAC, "02:00:00:00:00:01") in hub.connections

    light_device = devices.get(f"{SERIAL}_ch1")
    assert light_device is not None
    assert light_device.name == "Terrace"
    assert light_device.model == "Switch actuator"
    assert light_device.via_device_id == hub.id

    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    assert hass.states.get(light).state == STATE_OFF
    assert hass.states.get(light).name == "Terrace"
    cover = entity_id(hass, "cover", f"{SERIAL}_ch2")
    assert hass.states.get(cover).name == "Kitchen shade"
    assert len(er.async_entries_for_config_entry(er.async_get(hass), loaded_entry.entry_id)) > 2


async def test_unused_channels_are_skipped(hass: HomeAssistant, socket_enabled: None) -> None:
    from zeptrionair_api.testing import FakeChannel

    async with FakeZeptrionDevice(
        channels=[FakeChannel("1", name="Lamp"), FakeChannel("-1"), FakeChannel("00")], btfu=None
    ) as fake:
        entry = MockConfigEntry(domain=DOMAIN, unique_id=fake.serial, data={CONF_HOST: fake.host})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(hass.states.async_entity_ids("light")) == 1
        assert not hass.states.async_entity_ids("cover")
        assert not hass.states.async_entity_ids("event")  # no Smartfront
        await hass.config_entries.async_unload(entry.entry_id)


async def test_setup_retry_when_unreachable(hass: HomeAssistant, socket_enabled: None) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "127.0.0.1:9"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_unavailable_after_grace_period(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    fake.offline = True
    await fake.drop_websockets()
    coordinator = loaded_entry.runtime_data
    for _ in range(200):
        if coordinator._stream_down:
            break
        await asyncio.sleep(0.01)
    assert coordinator._stream_down
    await hass.async_block_till_done()
    # still available during the grace period
    assert hass.states.get(light).state == STATE_OFF

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert hass.states.get(light).state == STATE_UNAVAILABLE

    fake.offline = False
    await wait_for_state(hass, light, lambda s: s.state == STATE_OFF, timeout=10)


async def test_safety_poll(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    fake.channels[0].value = 100  # changed without a push
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await wait_for_state(hass, light, lambda s: s.state == "on")
