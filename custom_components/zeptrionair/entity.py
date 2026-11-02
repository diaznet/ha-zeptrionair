"""Base entities.

Each zApp device becomes a *hub* device (Wi-Fi signal, wall keys, temperature), and each used
channel becomes its own device named after the channel (light, cover, scene buttons). The channel
device's suggested area is the channel's group stored on the zApp.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from zeptrionair_api import Category, Channel

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZeptrionCoordinator

_MODELS = {
    Category.ONOFF: "Switch actuator",
    Category.DIMMER: "Dimmer",
    Category.BLIND: "Blind actuator",
    Category.AWNING: "Awning actuator",
}

# HA 2026.7 replaced DeviceInfo["via_device"] (identifier pair) by "via_device_id".
_HAS_VIA_DEVICE_ID = "via_device_id" in getattr(DeviceInfo, "__annotations__", {})


def hub_device_info(coordinator: ZeptrionCoordinator) -> DeviceInfo:
    """Device info of the zApp module itself (already registered in async_setup_entry)."""
    return DeviceInfo(identifiers={(DOMAIN, coordinator.info.serial)})


def channel_device_info(coordinator: ZeptrionCoordinator, channel: Channel) -> DeviceInfo:
    serial = coordinator.info.serial
    info: dict[str, Any] = {
        "identifiers": {(DOMAIN, f"{serial}_ch{channel.number}")},
        "manufacturer": MANUFACTURER,
        "model": _MODELS.get(channel.category, "Channel") if channel.category else "Channel",
        "name": channel.name or f"zApp-{serial} channel {channel.number}",
    }
    if channel.group:
        info["suggested_area"] = channel.group
    if _HAS_VIA_DEVICE_ID and coordinator.hub_device_id:
        info["via_device_id"] = coordinator.hub_device_id
    elif not _HAS_VIA_DEVICE_ID:  # pragma: no cover - Home Assistant before 2026.7
        info["via_device"] = (DOMAIN, serial)
    return DeviceInfo(**info)  # type: ignore[typeddict-item]


class ZeptrionEntity(CoordinatorEntity[ZeptrionCoordinator]):
    """Common base: availability follows the coordinator and the event stream."""

    _attr_has_entity_name = True

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data is not None and data.connected


class ZeptrionHubEntity(ZeptrionEntity):
    """Entity on the zApp module device."""

    def __init__(self, coordinator: ZeptrionCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.info.serial}_{key}"
        self._attr_device_info = hub_device_info(coordinator)


class ZeptrionChannelEntity(ZeptrionEntity):
    """Entity on a channel device."""

    def __init__(
        self, coordinator: ZeptrionCoordinator, channel: Channel, key: str | None = None
    ) -> None:
        super().__init__(coordinator)
        self.channel = channel
        base = f"{coordinator.info.serial}_ch{channel.number}"
        self._attr_unique_id = f"{base}_{key}" if key else base
        self._attr_device_info = channel_device_info(coordinator, channel)

    @property
    def value(self) -> int | None:
        data = self.coordinator.data
        return data.values.get(self.channel.number) if data else None
