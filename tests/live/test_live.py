"""Opt-in smoke test against real devices (skipped unless ZEPTRION_LIVE_HOSTS is set).

    ZEPTRION_LIVE_HOSTS="192.168.1.50 192.168.1.51" pytest tests/live -s
    # also switch a light on and back off (restoring its state):
    ZEPTRION_LIVE_LIGHT="192.168.1.50:1" ...

Use IP addresses: DNS resolution is disabled inside the Home Assistant test harness.

Covers are never moved by this test.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api import ZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN

HOSTS = os.environ.get("ZEPTRION_LIVE_HOSTS", "").split()
LIGHT = os.environ.get("ZEPTRION_LIVE_LIGHT", "")

pytestmark = pytest.mark.skipif(not HOSTS, reason="set ZEPTRION_LIVE_HOSTS to run")


@pytest.fixture
def allow_devices(socket_enabled: None) -> None:
    """The HA test harness only allows 127.0.0.1 (and no DNS); allow the device IPs."""
    import pytest_socket

    pytest_socket.socket_allow_hosts(["127.0.0.1", *(host.rsplit(":", 1)[0] for host in HOSTS)])


async def test_live_devices(hass: HomeAssistant, allow_devices: None) -> None:
    entries = []
    for host in HOSTS:
        async with ZeptrionDevice(host) as device:
            serial = (await device.identify()).serial
        entry = MockConfigEntry(domain=DOMAIN, unique_id=serial, data={CONF_HOST: host})
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        entries.append(entry)

        coordinator = entry.runtime_data
        registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        print(f"\n{host}: {coordinator.info.type} fw {coordinator.info.sw_version}")
        print(f"  capabilities: {coordinator.capabilities}")
        for reg in registered:
            state = hass.states.get(reg.entity_id)
            shown = state.state if state else f"(disabled: {reg.disabled_by})"
            print(f"  {reg.entity_id:<55} {shown}")
        assert any(r.domain in ("light", "cover") for r in registered)

    if LIGHT:
        host, channel = LIGHT.rsplit(":", 1)
        entry = next(e for e in entries if e.data[CONF_HOST] == host)
        entity_id = er.async_get(hass).async_get_entity_id(
            "light", DOMAIN, f"{entry.unique_id}_ch{channel}"
        )
        assert entity_id is not None
        await asyncio.sleep(1)  # let the event stream connect
        before = hass.states.get(entity_id).state
        target, restore = ("turn_off", "turn_on") if before == "on" else ("turn_on", "turn_off")
        expected = "off" if before == "on" else "on"

        start = time.monotonic()
        await hass.services.async_call("light", target, {"entity_id": entity_id}, blocking=True)
        while hass.states.get(entity_id).state != expected:
            assert time.monotonic() - start < 3, "state did not change within 3 s"
            await asyncio.sleep(0.01)
        elapsed = (time.monotonic() - start) * 1000
        print(f"\n{entity_id}: {before} -> {expected} in {elapsed:.0f} ms")

        await hass.services.async_call("light", restore, {"entity_id": entity_id}, blocking=True)
        start = time.monotonic()
        while hass.states.get(entity_id).state != before:
            assert time.monotonic() - start < 3
            await asyncio.sleep(0.01)
        print(f"{entity_id}: restored to {before}")

    for entry in entries:
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


COVER = os.environ.get("ZEPTRION_LIVE_COVER", "")


async def _wait(hass: HomeAssistant, entity_id: str, states: set[str], timeout: float) -> float:
    start = time.monotonic()
    while hass.states.get(entity_id).state not in states:
        assert time.monotonic() - start < timeout, f"{entity_id} never reached {states}"
        await asyncio.sleep(0.05)
    return time.monotonic() - start


@pytest.mark.skipif(not COVER, reason="set ZEPTRION_LIVE_COVER=ip:channel to move a cover")
async def test_live_cover(hass: HomeAssistant, allow_devices: None) -> None:
    """MOVES THE COVER: 1 s step down/up, full close, full open (ends fully open)."""
    host, channel = COVER.rsplit(":", 1)
    async with ZeptrionDevice(host) as device:
        serial = (await device.identify()).serial
    entry = MockConfigEntry(domain=DOMAIN, unique_id=serial, data={CONF_HOST: host})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(1)
    cover = er.async_get(hass).async_get_entity_id("cover", DOMAIN, f"{serial}_ch{channel}")
    assert cover is not None
    print(f"\n{cover}: start state {hass.states.get(cover).state}")

    async def call(domain: str, service: str, **data: object) -> None:
        await hass.services.async_call(domain, service, {"entity_id": cover, **data}, blocking=True)

    await call(DOMAIN, "move_step", direction="down", duration=1000)
    await _wait(hass, cover, {"closing"}, 5)
    await _wait(hass, cover, {"open", "closed"}, 10)
    print(f"step down 1 s -> {hass.states.get(cover).state} (expected: open)")
    assert hass.states.get(cover).state == "open"
    await call(DOMAIN, "move_step", direction="up", duration=1000)
    await _wait(hass, cover, {"opening"}, 5)
    await _wait(hass, cover, {"open", "closed"}, 10)
    print(f"step up 1 s -> {hass.states.get(cover).state}")

    await call("cover", "close_cover")
    await _wait(hass, cover, {"closing"}, 5)
    down = await _wait(hass, cover, {"closed", "open"}, 180)
    print(f"full close -> {hass.states.get(cover).state} after {down:.1f} s (travel time down)")
    assert hass.states.get(cover).state == "closed"

    await call("cover", "open_cover")
    await _wait(hass, cover, {"opening"}, 5)
    up = await _wait(hass, cover, {"open", "closed"}, 180)
    print(f"full open -> {hass.states.get(cover).state} after {up:.1f} s (travel time up)")
    assert hass.states.get(cover).state == "open"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
