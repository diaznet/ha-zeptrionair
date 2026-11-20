"""Base entities.

Each zApp device becomes a *hub* device (Wi-Fi signal, wall keys, temperature), and each used
channel becomes its own device named after the channel (light, cover, scene buttons). The channel
device's suggested area is the channel's group stored on the zApp.
"""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from zeptrionair_api import Category, Channel, ZeptrionError, scene_command

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZeptrionCoordinator

_MODELS = {
    Category.ONOFF: "Switch actuator",
    Category.DIMMER: "Dimmer",
    Category.BLIND: "Blind actuator",
    Category.AWNING: "Awning actuator",
}
CHANNEL_TEXT_BYTES = 32  # name and group on the zApp, UTF-8 bytes

# HA 2026.7 replaced DeviceInfo["via_device"] (identifier pair) by "via_device_id".
_HAS_VIA_DEVICE_ID = "via_device_id" in getattr(DeviceInfo, "__annotations__", {})


def truncate_utf8(text: str, limit: int = CHANNEL_TEXT_BYTES) -> str:
    """Cut ``text`` to at most ``limit`` UTF-8 bytes without splitting a character."""
    encoded = text.strip().encode("utf-8")
    if len(encoded) <= limit:
        return text.strip()
    return encoded[:limit].decode("utf-8", errors="ignore").rstrip()


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


def command_error(err: ZeptrionError) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"error": str(err)},
    )


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

    async def send_command(self, command: str) -> None:
        """Send a channel command, turning library errors into Home Assistant errors."""
        try:
            await self.coordinator.device.send(self.channel.number, command)
        except ZeptrionError as err:
            raise command_error(err) from err


class ZeptrionMainChannelEntity(ZeptrionChannelEntity):
    """The light or cover of a channel. Target of the integration's actions."""

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        registry: dict[str, ZeptrionMainChannelEntity] = self.hass.data.setdefault(DOMAIN, {})
        registry[self.entity_id] = self
        self.async_on_remove(lambda: registry.pop(self.entity_id, None))

    # Scenes are stored on the zApp itself (like holding a scene key on the wall).

    async def async_store_scene(self, scene: int) -> None:
        await self.send_command(scene_command("store", scene))
        self.scene_stored(scene)

    async def async_recall_scene(self, scene: int) -> None:
        self.scene_recalling(scene)
        await self.send_command(scene_command("recall", scene))
        self.async_write_ha_state()

    def scene_stored(self, scene: int) -> None:
        """Hook: a scene was stored through Home Assistant."""

    def scene_recalling(self, scene: int) -> None:
        """Hook: Home Assistant is about to recall a scene."""

    async def async_write_name(self, name: str | None = None, group: str | None = None) -> None:
        """Write a name and group (room) to the zApp, so the Feller app shows them too.

        Defaults: the name of this channel's device in Home Assistant, and its area.
        """
        device = (
            dr.async_get(self.hass).async_get(self.device_entry.id) if self.device_entry else None
        )
        if not name:
            name = (device.name_by_user or device.name) if device else self.name
        if group is None:
            area_id = None
            entry = er.async_get(self.hass).async_get(self.entity_id)
            if entry is not None and entry.area_id:
                area_id = entry.area_id
            elif device is not None:
                area_id = device.area_id
            area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
            group = area.name if area else ""
        fields = {"name": truncate_utf8(str(name or "")), "group": truncate_utf8(group)}
        try:
            await self.coordinator.device.set_channel_description(self.channel.number, **fields)
            self.coordinator.channels = await self.coordinator.device.channels()
        except ZeptrionError as err:
            raise command_error(err) from err
