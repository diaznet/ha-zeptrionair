"""Integration actions: store/recall scenes, cover steps, write names to the zApp.

Registered once in ``async_setup`` (not per config entry), so they work for every zApp. Targets
are resolved to this integration's light and cover entities.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .const import (
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_GROUP,
    ATTR_NAME,
    ATTR_SCENE,
    DOMAIN,
    SERVICE_MOVE_STEP,
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
        SERVICE_WRITE_NAME,
        _handler(
            hass, lambda e, c: e.async_write_name(c.data.get(ATTR_NAME), c.data.get(ATTR_GROUP))
        ),
        schema=NAME_SCHEMA,
    )
