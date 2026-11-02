"""Fixtures: a simulated zApp device (from zeptrionair_api.testing) and config entries."""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api import events as api_events
from zeptrionair_api.testing import FakeChannel, FakeZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN

SERIAL = "99990001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    yield


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_events, "BACKOFF_MIN", 0.01)
    monkeypatch.setattr(api_events, "BACKOFF_MAX", 0.05)


def default_channels() -> list[FakeChannel]:
    return [
        FakeChannel("1", name="Terrace", group="Garden"),
        FakeChannel("5", name="Kitchen shade", group="Kitchen", travel_time=100),
    ]


@pytest.fixture
def channels() -> list[FakeChannel]:
    return default_channels()


@pytest.fixture
def btfu() -> str | None:
    """ch1 on/off on keys 5/6, ch2 up/down on keys 7/8, Smartbuttons on keys 3/4."""
    return "0,0,1000,1000,8501,8602,4501,4602"


@pytest.fixture
async def fake(
    hass: HomeAssistant, socket_enabled: None, channels: list[FakeChannel], btfu: str | None
) -> AsyncIterator[FakeZeptrionDevice]:
    device = FakeZeptrionDevice(serial=SERIAL, channels=channels, btfu=btfu, time_scale=0.01)
    await device.start()
    yield device
    await hass.async_block_till_done()
    # Unload every entry first, so nothing reconnects to a stopping server.
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    await device.stop()


@pytest.fixture
def entry(fake: FakeZeptrionDevice) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        title=f"zApp-{SERIAL}",
        data={CONF_HOST: fake.host},
    )


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> AsyncIterator[MockConfigEntry]:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await wait_for_stream(hass, fake)
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def wait_for_stream(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    """Wait until the integration's event stream is connected and has read its snapshot."""
    import asyncio

    for _ in range(300):
        if fake._clients and any(path == "/zrap/chscan" for _, path, _ in fake.requests[-3:]):
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()


def entity_id(hass: HomeAssistant, platform: str, unique_id: str) -> str:
    """Entity ID from the unique ID (HA prefixes entity IDs with the area name)."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert found is not None, f"no {platform} entity with unique_id {unique_id}"
    return found


async def wait_for_state(
    hass: HomeAssistant, entity_id: str, check: object, timeout: float = 3.0
) -> None:
    """Wait until ``check(state)`` is true (the device pushes changes asynchronously)."""
    import asyncio

    async def poll() -> None:
        while True:
            await hass.async_block_till_done()
            state = hass.states.get(entity_id)
            if state is not None and check(state):  # type: ignore[operator]
                return
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)
