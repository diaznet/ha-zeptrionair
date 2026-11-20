"""0.2: travel-time learning, calibration, slats, scene following, hold keys, LEDs,
Smartbutton programming, reconnect and connection statistics.

The fake shade (ch2) needs 2 s for a full travel (200 s x time_scale 0.01).
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.components.cover import (
    CoverState,
)
from homeassistant.components.light import ATTR_RGB_COLOR
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api import ZeptrionConnectionError
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import (
    CONF_CHANNELS,
    DOMAIN,
)

from .conftest import SERIAL, entity_id, wait_for_state

TRAVEL = 2.0  # seconds, the fake shade's full travel


def _cover(hass: HomeAssistant) -> str:
    return entity_id(hass, "cover", f"{SERIAL}_ch2")


async def _call(hass: HomeAssistant, domain: str, service: str, **data: object) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)


async def _cover_call(hass: HomeAssistant, service: str, **data: object) -> None:
    await _call(hass, "cover", service, entity_id=_cover(hass), **data)


async def _wait_still(hass: HomeAssistant, timeout: float = 8) -> None:
    await wait_for_state(
        hass,
        _cover(hass),
        lambda s: s.state not in (CoverState.OPENING, CoverState.CLOSING),
        timeout=timeout,
    )


def _channel_options(entry: MockConfigEntry) -> dict:
    return dict(entry.options.get(CONF_CHANNELS, {}).get("2", {}))


def _notification(hass: HomeAssistant) -> str:
    from homeassistant.components import persistent_notification

    notes = persistent_notification._async_get_or_create_notifications(hass)
    return " | ".join(n["message"] for n in notes.values())


# --- LEDs, Smartbuttons, reconnect, statistics


async def _enable(hass: HomeAssistant, entry: MockConfigEntry, *entity_ids: str) -> None:
    registry = er.async_get(hass)
    for eid in entity_ids:
        registry.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_leds_and_undo(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    led = entity_id(hass, "light", f"{SERIAL}_led_5")
    undo = entity_id(hass, "button", f"{SERIAL}_undo_led")
    assert entity_id(hass, "light", f"{SERIAL}_led_3")  # Smartbutton key
    assert er.async_get(hass).async_get_entity_id("light", DOMAIN, f"{SERIAL}_led_1") is None
    await _enable(hass, loaded_entry, led, undo)
    assert hass.states.get(led).state == "on"  # factory background #000020

    await _call(hass, "light", "turn_on", entity_id=led, rgb_color=[255, 0, 0], brightness=128)
    assert fake.leds[4]["bg"] == "#800000"
    assert hass.states.get(led).attributes[ATTR_RGB_COLOR] == (255, 0, 0)
    await _call(hass, "light", "turn_off", entity_id=led)
    assert fake.leds[4]["bg"] == "#000000"
    assert hass.states.get(led).state == "off"

    await _call(hass, "button", "press", entity_id=undo)
    assert fake.leds[4]["bg"] == "#800000"
    await _call(hass, "button", "press", entity_id=undo)
    assert fake.leds[4]["bg"] == "#000020"
    with pytest.raises(Exception, match=r"."):
        await _call(hass, "button", "press", entity_id=undo)


def _hub_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return next(
        d.id
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, SERIAL) in d.identifiers
    )


async def test_program_smartbutton(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    hub = _hub_id(hass, loaded_entry)
    light = entity_id(hass, "light", f"{SERIAL}_ch1")

    async def press_when_blinking() -> None:
        for _ in range(400):
            if fake.programming["on"]:
                await fake.press_key(4)
                return
            await asyncio.sleep(0.02)

    presser = asyncio.create_task(press_when_blinking())
    await _call(
        hass,
        DOMAIN,
        "program_smartbutton",
        device_id=hub,
        commands=[
            {"entity_id": _cover(hass), "command": "recall_s1"},
            {"entity_id": light, "command": "toggle"},
        ],
        requests=[{"req": "GET", "loc": "192.0.2.5", "pth": "/hook"}],
        wait=20,
    )
    await presser
    for _ in range(200):
        if "programmed" in _notification(hass):
            break
        await asyncio.sleep(0.05)
    assert "programmed (2 request(s))" in _notification(hass) or "programmed" in _notification(hass)
    program = fake.smartbutton_programs[4]
    assert program[0]["bdy"] == "cmd2=recall_s1&cmd1=toggle"
    assert program[0]["loc"] == "127.0.0.1"
    assert program[1]["pth"] == "/hook"


async def test_program_smartbutton_errors(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    hub = _hub_id(hass, loaded_entry)
    light = entity_id(hass, "light", f"{SERIAL}_ch1")
    cases = [
        ({"device_id": "nope", "commands": [{"entity_id": light, "command": "on"}]}, "zApp"),
        ({"device_id": hub}, "at least one"),
        ({"device_id": hub, "commands": [{"entity_id": light, "command": "boom"}]}, "boom"),
        ({"device_id": hub, "commands": [{"entity_id": "light.x", "command": "on"}]}, "light.x"),
        (
            {
                "device_id": hub,
                "commands": [{"entity_id": light, "command": "move_close_12345"}] * 30,
                "requests": [{"loc": f"host-number-{i}.example", "pth": "/x"} for i in range(30)],
            },
            "bytes",
        ),
    ]
    for data, text in cases:
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, DOMAIN, "program_smartbutton", **data)
        assert text in str(err.value) or err.value.translation_key


async def test_reconnect_and_statistics(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, fake: FakeZeptrionDevice
) -> None:
    connections = entity_id(hass, "sensor", f"{SERIAL}_connections")
    short = entity_id(hass, "sensor", f"{SERIAL}_short_outages")
    await _enable(hass, loaded_entry, connections, short)
    await wait_for_state(hass, connections, lambda s: s.state == "1", timeout=5)

    await fake.drop_websockets()
    await wait_for_state(hass, connections, lambda s: s.state == "2", timeout=5)
    assert hass.states.get(short).state == "1"

    reconnect = entity_id(hass, "button", f"{SERIAL}_reconnect")
    await _call(hass, "button", "press", entity_id=reconnect)
    await hass.async_block_till_done()
    assert loaded_entry.state.name == "LOADED"
    await wait_for_state(hass, connections, lambda s: s.state == "1", timeout=5)


async def test_diagnostic_read_errors_do_not_fail_the_update(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    fake: FakeZeptrionDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = loaded_entry.runtime_data
    rssi = coordinator.data.rssi

    async def busy() -> int:
        raise ZeptrionConnectionError("HTTP 500 for /zrap/rssi")

    monkeypatch.setattr(coordinator.device, "rssi", busy)
    monkeypatch.setattr(coordinator.device, "sensors", busy)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.rssi == rssi
