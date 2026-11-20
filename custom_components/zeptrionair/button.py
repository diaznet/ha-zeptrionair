"""Buttons: recall and store scenes (1-4, stored on the zApp), cover steps."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from zeptrionair_api import Channel

from .const import DOMAIN
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionChannelEntity, ZeptrionMainChannelEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for channel in coordinator.used_channels:
        for scene in range(1, 5):
            entities.append(ZeptrionSceneButton(coordinator, channel, scene, store=False))
            entities.append(ZeptrionSceneButton(coordinator, channel, scene, store=True))
        if channel.category is not None and channel.category.is_cover:
            entities.append(ZeptrionStepButton(coordinator, channel, "up"))
            entities.append(ZeptrionStepButton(coordinator, channel, "down"))
    async_add_entities(entities)


class _ChannelButton(ZeptrionChannelEntity, ButtonEntity):
    """A button acting through the channel's light or cover entity."""

    async def _with_main_entity(
        self, action: Callable[[ZeptrionMainChannelEntity], Awaitable[None]]
    ) -> None:
        main_id = er.async_get(self.hass).async_get_entity_id(
            "cover" if self.channel.category and self.channel.category.is_cover else "light",
            DOMAIN,
            f"{self.coordinator.info.serial}_ch{self.channel.number}",
        )
        main = self.hass.data.get(DOMAIN, {}).get(main_id) if main_id else None
        if main is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="entity_missing")
        await action(main)


class ZeptrionSceneButton(_ChannelButton):
    """Recall or store one of the four scenes of a channel."""

    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: ZeptrionCoordinator, channel: Channel, scene: int, *, store: bool
    ) -> None:
        super().__init__(coordinator, channel, f"{'store' if store else 'scene'}_{scene}")
        self._scene = scene
        self._store = store
        self._attr_translation_key = "store_scene" if store else "recall_scene"
        self._attr_translation_placeholders = {"scene": str(scene)}
        if store:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        if self._store:
            await self._with_main_entity(lambda main: main.async_store_scene(self._scene))
        else:
            await self._with_main_entity(lambda main: main.async_recall_scene(self._scene))


class ZeptrionStepButton(_ChannelButton):
    """Move a cover a short step (the step duration from the options)."""

    def __init__(self, coordinator: ZeptrionCoordinator, channel: Channel, direction: str) -> None:
        super().__init__(coordinator, channel, f"step_{direction}")
        self._direction = direction
        self._attr_translation_key = f"step_{direction}"

    async def async_press(self) -> None:
        await self._with_main_entity(
            lambda main: main.async_move_step(self._direction)  # type: ignore[attr-defined]
        )
