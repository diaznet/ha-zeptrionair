"""Integration actions: scenes, cover steps and calibration, names, Smartbutton programming.

Registered once in ``async_setup`` (not per config entry), so they work for every zApp. Targets
are resolved to this integration's light and cover entities.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service
from homeassistant.helpers.translation import async_get_translations
from zeptrionair_api import (
    SmartbuttonProgramTooLongError,
    ZeptrionError,
    ZeptrionNotSupportedError,
    channel_request,
    validate_command,
)
from zeptrionair_api.smartbutton import MAX_REQUEST_BYTES, encode, request_size

from .const import (
    ATTR_COMMAND,
    ATTR_COMMANDS,
    ATTR_DEVICE_ID,
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_GROUP,
    ATTR_NAME,
    ATTR_REQUESTS,
    ATTR_SCENE,
    ATTR_WAIT,
    DOMAIN,
    SERVICE_CALIBRATE,
    SERVICE_MOVE_STEP,
    SERVICE_PROGRAM_SMARTBUTTON,
    SERVICE_RECALL_SCENE,
    SERVICE_STORE_SCENE,
    SERVICE_WRITE_NAME,
)
from .entity import ZeptrionMainChannelEntity

SCENE_SCHEMA = cv.make_entity_service_schema(
    {vol.Required(ATTR_SCENE): vol.All(vol.Coerce(int), vol.Range(min=1, max=4))}
)
STEP_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_DIRECTION): vol.In(["up", "down"]),
        vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=100, max=32000)),
    }
)
NAME_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional(ATTR_NAME): cv.string, vol.Optional(ATTR_GROUP): cv.string}
)
CALIBRATE_SCHEMA = cv.make_entity_service_schema({})
SMARTBUTTON_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_COMMANDS, default=list): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {vol.Required("entity_id"): cv.entity_id, vol.Required(ATTR_COMMAND): cv.string}
                )
            ],
        ),
        vol.Optional(ATTR_REQUESTS, default=list): vol.All(
            cv.ensure_list, [vol.Schema({cv.string: vol.Coerce(str)})]
        ),
        vol.Optional(ATTR_WAIT, default=60): vol.All(vol.Coerce(int), vol.Range(min=10, max=120)),
    }
)

_LOGGER = logging.getLogger(__name__)

# HA 2026 dropped the ``hass`` argument of async_extract_entity_ids.
_EXTRACT_TAKES_HASS = "hass" in inspect.signature(service.async_extract_entity_ids).parameters


async def _entities(hass: HomeAssistant, call: ServiceCall, domain: str | None = None) -> list[Any]:
    if _EXTRACT_TAKES_HASS:  # pragma: no cover - Home Assistant before 2026
        entity_ids = await service.async_extract_entity_ids(hass, call)  # type: ignore[call-arg]
    else:
        entity_ids = await service.async_extract_entity_ids(call)  # type: ignore[call-arg]
    registry: dict[str, ZeptrionMainChannelEntity] = hass.data.get(DOMAIN, {})
    entities = [
        registry[entity_id]
        for entity_id in sorted(entity_ids)
        if entity_id in registry and (domain is None or entity_id.startswith(f"{domain}."))
    ]
    if not entities:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_target")
    return entities


def _error(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders
    )


async def _notify(hass: HomeAssistant, key: str, notification_id: str, **placeholders: str) -> None:
    translations = await async_get_translations(hass, hass.config.language, "exceptions", {DOMAIN})
    template = translations.get(f"component.{DOMAIN}.exceptions.{key}.message", key)
    try:
        message = template.format(**placeholders)
    except (KeyError, IndexError):
        message = template
    persistent_notification.async_create(
        hass, message, title="Feller zeptrionAir", notification_id=notification_id
    )


async def _program_smartbutton(hass: HomeAssistant, call: ServiceCall) -> None:
    """Program a Smartbutton of one zApp with commands for lights/covers of any zApp."""
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    coordinator = None
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.hub_device_id != call.data[ATTR_DEVICE_ID]:
        raise _error("not_a_zapp")
    if not coordinator.capabilities.smartbuttons:
        raise _error("no_smartbuttons")

    registry: dict[str, ZeptrionMainChannelEntity] = hass.data.get(DOMAIN, {})
    requests: list[dict[str, str]] = []
    for item in call.data[ATTR_COMMANDS]:
        entity = registry.get(item["entity_id"])
        if entity is None:
            raise _error("unknown_entity", entity_id=item["entity_id"])
        try:
            command = validate_command(item[ATTR_COMMAND])
            requests.append(
                channel_request(entity.coordinator.device.host, entity.channel.number, command)
            )
        except ValueError as err:
            raise _error("invalid_command", command=item[ATTR_COMMAND]) from err
    requests.extend(dict(request) for request in call.data[ATTR_REQUESTS])
    if not requests:
        raise _error("no_commands")
    try:
        size = request_size(coordinator.device.host, encode(requests))
    except ValueError as err:
        raise _error("invalid_request", error=str(err)) from err
    if size > MAX_REQUEST_BYTES:
        raise _error("program_too_long", size=str(size), limit=str(MAX_REQUEST_BYTES))

    wait = call.data[ATTR_WAIT]
    name = device.name_by_user or device.name or "zApp"
    notification_id = f"{DOMAIN}_smartbutton_{coordinator.info.serial}"

    async def program() -> None:
        await _notify(hass, "smartbutton_press_now", notification_id, name=name, wait=str(wait))
        try:
            pressed = await coordinator.device.program_smartbutton(requests, wait=wait)
        except (ZeptrionError, SmartbuttonProgramTooLongError) as err:
            if isinstance(err, ZeptrionNotSupportedError):
                await _notify(hass, "no_smartbuttons", notification_id)
            else:
                await _notify(hass, "smartbutton_failed", notification_id, error=str(err))
            return
        key = "smartbutton_programmed" if pressed else "smartbutton_not_pressed"
        await _notify(hass, key, notification_id, name=name, count=str(len(requests)))

    hass.async_create_background_task(program(), f"{DOMAIN} program Smartbutton")


def _handler(
    hass: HomeAssistant,
    action: Callable[[Any, ServiceCall], Awaitable[None]],
    domain: str | None = None,
) -> Callable[[ServiceCall], Awaitable[None]]:
    async def handle(call: ServiceCall) -> None:
        for entity in await _entities(hass, call, domain):
            await action(entity, call)

    return handle


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    hass.services.async_register(
        DOMAIN,
        SERVICE_STORE_SCENE,
        _handler(hass, lambda e, c: e.async_store_scene(c.data[ATTR_SCENE])),
        schema=SCENE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECALL_SCENE,
        _handler(hass, lambda e, c: e.async_recall_scene(c.data[ATTR_SCENE])),
        schema=SCENE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MOVE_STEP,
        _handler(
            hass,
            lambda e, c: e.async_move_step(c.data[ATTR_DIRECTION], c.data.get(ATTR_DURATION)),
            "cover",
        ),
        schema=STEP_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALIBRATE,
        _handler(hass, lambda e, c: e.async_calibrate(), "cover"),
        schema=CALIBRATE_SCHEMA,
    )

    async def program(call: ServiceCall) -> None:
        await _program_smartbutton(hass, call)

    hass.services.async_register(
        DOMAIN, SERVICE_PROGRAM_SMARTBUTTON, program, schema=SMARTBUTTON_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_NAME,
        _handler(
            hass, lambda e, c: e.async_write_name(c.data.get(ATTR_NAME), c.data.get(ATTR_GROUP))
        ),
        schema=NAME_SCHEMA,
    )
