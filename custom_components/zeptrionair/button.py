"""Buttons: scenes (1-4, stored on the zApp), cover steps and calibration, reconnect,
undo the last Smartfront LED change."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from zeptrionair_api import Channel, ZeptrionError

from .const import DOMAIN
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import (
    ZeptrionChannelEntity,
    ZeptrionHubEntity,
    ZeptrionMainChannelEntity,
    command_error,
)

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
            entities.append(ZeptrionCalibrateButton(coordinator, channel))
    entities.append(ZeptrionReconnectButton(coordinator))
    if coordinator.led_colors:
        entities.append(ZeptrionUndoLedButton(coordinator))
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


class ZeptrionCalibrateButton(_ChannelButton):
    """Measure the travel times of a cover (fully up, down, up, back)."""

    _attr_translation_key = "calibrate"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ZeptrionCoordinator, channel: Channel) -> None:
        super().__init__(coordinator, channel, "calibrate")

    async def async_press(self) -> None:
        await self._with_main_entity(lambda main: main.async_calibrate())  # type: ignore[attr-defined]


class ZeptrionReconnectButton(ZeptrionHubEntity, ButtonEntity):
    """Reload this zApp in Home Assistant (connection, states, entities).

    The zApp itself can't be restarted remotely; a zApp that doesn't answer needs a short
    power cut.
    """

    _attr_translation_key = "reconnect"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ZeptrionCoordinator) -> None:
        super().__init__(coordinator, "reconnect")

    @property
    def available(self) -> bool:
        return True  # most useful exactly when the zApp is unavailable

    async def async_press(self) -> None:
        self.hass.config_entries.async_schedule_reload(self.coordinator.config_entry.entry_id)


class ZeptrionUndoLedButton(ZeptrionHubEntity, ButtonEntity):
    """Undo the last Smartfront LED colour change made in Home Assistant."""

    _attr_translation_key = "undo_led"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ZeptrionCoordinator) -> None:
        super().__init__(coordinator, "undo_led")

    async def async_press(self) -> None:
        coordinator = self.coordinator
        if not coordinator.led_history:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="nothing_to_undo")
        change = coordinator.led_history.pop()
        try:
            await coordinator.device.set_led_backgrounds(change)
        except ZeptrionError as err:
            coordinator.led_history.append(change)
            raise command_error(err) from err
        coordinator.led_colors.update(change)
        coordinator.async_update_listeners()
