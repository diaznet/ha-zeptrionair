"""Diagnostics download (identifying values redacted)."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import ZeptrionConfigEntry

TO_REDACT = {CONF_HOST, "serial", "mac", "name", "group", "title", "unique_id"}


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZeptrionConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = {
        "entry": {"data": dict(entry.data), "options": dict(entry.options), "title": entry.title},
        "device": _plain(coordinator.info),
        "mac": coordinator.mac,
        "capabilities": _plain(coordinator.capabilities),
        "channels": _plain(coordinator.channels),
        "smartfront": _plain(coordinator.smartfront),
        "state": _plain(coordinator.data),
        "last_update_success": coordinator.last_update_success,
    }
    return async_redact_data(data, TO_REDACT)
