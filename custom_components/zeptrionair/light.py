"""Lights: on/off channels (category 1) and dimmers (category 3).

Dimmers are reported to answer ``100`` whenever they're lit, whatever the brightness, so the
brightness can't be read back. It is tracked optimistically instead: Home Assistant remembers
the brightness it set (also across restarts), and a pushed ``100`` only means "on". If a device
does report 1-99, that value is used.

The zApp has no "set brightness" command. A brightness is reached by dimming for a computed
time: from the known current brightness when the light is on, otherwise by switching on (100 %)
and dimming down.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from zeptrionair_api import Category, Channel, timed_command
from zeptrionair_api.const import TIMED_MAX_MS, TIMED_MIN_MS

from .const import CONF_DIM_TIME, DEFAULT_DIM_TIME
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionMainChannelEntity
from .options import channel_options

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
_FULL = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZeptrionLight(coordinator, channel)
        for channel in coordinator.used_channels
        if channel.category is not None and channel.category.is_light
    )


class _LightExtraData(ExtraStoredData):
    def __init__(self, brightness: int | None, scenes: dict[int, int]) -> None:
        self.brightness = brightness
        self.scenes = scenes

    def as_dict(self) -> dict[str, Any]:
        return {
            "brightness": self.brightness,
            "scenes": {str(k): v for k, v in self.scenes.items()},
        }


class ZeptrionLight(ZeptrionMainChannelEntity, LightEntity, RestoreEntity):
    """A light channel. The entity is the main feature of its channel device."""

    _attr_name = None

    def __init__(self, coordinator: ZeptrionCoordinator, channel: Channel) -> None:
        super().__init__(coordinator, channel)
        self._dimmer = channel.category is Category.DIMMER
        mode = ColorMode.BRIGHTNESS if self._dimmer else ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}
        options = channel_options(coordinator.config_entry, channel.number)
        self._dim_time = int(options.get(CONF_DIM_TIME, DEFAULT_DIM_TIME))
        self._brightness: int = _FULL  # last known brightness while on (optimistic)
        self._scenes: dict[int, int] = {}  # brightness of scenes stored through HA (0 = off)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self._dimmer:
            return
        if (extra := await self.async_get_last_extra_data()) is not None:
            data = extra.as_dict()
            if isinstance(data.get("brightness"), int) and data["brightness"] > 0:
                self._brightness = data["brightness"]
            scenes = data.get("scenes")
            if isinstance(scenes, dict):
                self._scenes = {int(k): int(v) for k, v in scenes.items() if str(k).isdigit()}
        self._apply_reported(self.value)

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        return _LightExtraData(self._brightness, self._scenes) if self._dimmer else None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._apply_reported(self.value)
        super()._handle_coordinator_update()

    def _apply_reported(self, value: int | None) -> None:
        """A reported 1-99 is a real level; 100 only means "on" (keep the known brightness)."""
        if not self._dimmer or value is None:
            return
        if 0 < value < 100:
            self._brightness = max(1, round(value * _FULL / 100))

    @property
    def is_on(self) -> bool | None:
        value = self.value
        return None if value is None else value > 0

    @property
    def brightness(self) -> int | None:
        if not self._dimmer or not self.is_on:
            return None
        return self._brightness

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._dimmer or not self._scenes:
            return None
        return {f"scene_{n}_brightness": b for n, b in sorted(self._scenes.items())}

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if not self._dimmer or brightness is None:
            await self.send_command("on")
            if self._dimmer:
                self._brightness = _FULL  # "on" switches a dimmer to 100 %
                self.async_write_ha_state()
            return
        await self._dim_to(max(1, min(_FULL, int(brightness))))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send_command("off")

    async def _dim_to(self, target: int) -> None:
        """Reach ``target`` (1-255) by dimming for a computed time (optimistic)."""
        if self.is_on:
            current = self._brightness
        else:
            await self.send_command("on")
            current = _FULL
        delta = (target - current) / _FULL  # fraction of the full range
        milliseconds = round(abs(delta) * self._dim_time)
        if milliseconds >= TIMED_MIN_MS:
            action = "dim_up" if delta > 0 else "dim_down"
            await self.send_command(timed_command(action, min(TIMED_MAX_MS, milliseconds)))
        _LOGGER.debug(
            "ch%s: brightness %s -> %s (dimmed %s ms)",
            self.channel.number,
            current,
            target,
            milliseconds if milliseconds >= TIMED_MIN_MS else 0,
        )
        self._brightness = target
        self.async_write_ha_state()

    # Scenes: the zApp stores on/off and the dim level, but only reports "on" when recalled.
    # Scenes stored through Home Assistant are remembered, so a recall shows their brightness.

    def scene_stored(self, scene: int) -> None:
        if self._dimmer:
            self._scenes[scene] = self._brightness if self.is_on else 0
            self.async_write_ha_state()

    def scene_recalling(self, scene: int) -> None:
        stored = self._scenes.get(scene) if self._dimmer else None
        if stored:  # on/off follows the device's push; the level is known only to us
            self._brightness = stored
