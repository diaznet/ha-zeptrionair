"""Scene recall buttons (scenes 1-4 stored on the device), disabled by default."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from zeptrionair_api import Channel, ZeptrionError, scene_command

from .const import DOMAIN
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionChannelEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZeptrionSceneButton(coordinator, channel, scene)
        for channel in coordinator.used_channels
        for scene in range(1, 5)
    )


class ZeptrionSceneButton(ZeptrionChannelEntity, ButtonEntity):
    """Recall one of the four scenes of a channel."""

    _attr_translation_key = "recall_scene"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ZeptrionCoordinator, channel: Channel, scene: int) -> None:
        super().__init__(coordinator, channel, f"scene_{scene}")
        self._scene = scene
        self._attr_translation_placeholders = {"scene": str(scene)}

    async def async_press(self) -> None:
        try:
            await self.coordinator.device.send(
                self.channel.number, scene_command("recall", self._scene)
            )
        except ZeptrionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
