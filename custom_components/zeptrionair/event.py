"""Event entities for the Smartfront keys (wall keys and Smartbuttons)."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from zeptrionair_api import KeyEvent, KeyFunction

from .const import EVENT_PRESS, EVENT_RELEASE
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionHubEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.smartfront is None:
        return
    async_add_entities(
        ZeptrionKeyEvent(coordinator, key)
        for key in coordinator.smartfront.keys
        if key.kind != "unused"
    )


class ZeptrionKeyEvent(ZeptrionHubEntity, EventEntity):
    """One Smartfront key. Fires ``press`` and ``release``."""

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, coordinator: ZeptrionCoordinator, key: KeyFunction) -> None:
        super().__init__(coordinator, f"key_{key.key}")
        self._attr_event_types = [EVENT_PRESS, EVENT_RELEASE]
        self._key = key
        self._attr_translation_key = "smartbutton" if key.kind == "smartbutton" else "key"
        self._attr_translation_placeholders = {"key": str(key.key)}
        attributes: dict[str, object] = {"function": key.kind, "code": key.raw}
        if key.kind == "channel":
            attributes["channels"] = sorted(key.channels)
            attributes["direction"] = key.direction
        self._attributes = attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_key_listener(self._handle_key))

    @callback
    def _handle_key(self, event: KeyEvent) -> None:
        if event.key != self._key.key:
            return
        self._trigger_event(EVENT_PRESS if event.pressed else EVENT_RELEASE, self._attributes)
        self.async_write_ha_state()
