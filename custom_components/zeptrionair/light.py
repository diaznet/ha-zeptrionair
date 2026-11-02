"""Lights: on/off channels (category 1) and dimmers (category 3)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from zeptrionair_api import Category, Channel, ZeptrionError, timed_command
from zeptrionair_api.const import TIMED_MAX_MS, TIMED_MIN_MS

from .const import CONF_DIM_TIME, DEFAULT_DIM_TIME, DOMAIN
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionChannelEntity
from .options import channel_options

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
_TOLERANCE = 3  # % close enough
_CORRECTION_THRESHOLD = 10  # % error that triggers one correction


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


class ZeptrionLight(ZeptrionChannelEntity, LightEntity):
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

    @property
    def is_on(self) -> bool | None:
        value = self.value
        return None if value is None else value > 0

    @property
    def brightness(self) -> int | None:
        if not self._dimmer or self.value is None:
            return None
        return round(self.value * 255 / 100)

    async def _send(self, command: str) -> None:
        try:
            await self.coordinator.device.send(self.channel.number, command)
        except ZeptrionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if not self._dimmer or brightness is None:
            await self._send("on")
            return
        await self._dim_to(max(1, round(brightness * 100 / 255)))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send("off")

    async def _dim_to(self, target: int) -> None:
        """Approach a brightness by dimming for a computed time (experimental).

        The device can only dim for a duration, so: switch on if needed, dim for
        |delta| x full-range time, then make one correction if the result is far off.
        """
        number = self.channel.number
        current = self.value or 0
        if current == 0:
            await self._send("on")
            current = await self.coordinator.async_wait_for(number, lambda v: bool(v), 3) or 0
        for attempt in range(2):
            delta = target - current
            if abs(delta) <= (_TOLERANCE if attempt == 0 else _CORRECTION_THRESHOLD):
                return
            duration = round(abs(delta) / 100 * self._dim_time)
            duration = min(TIMED_MAX_MS, max(TIMED_MIN_MS, duration))
            await self._send(timed_command("dim_up" if delta > 0 else "dim_down", duration))
            previous = current
            current = (
                await self.coordinator.async_wait_for(
                    number, lambda v, p=previous: v is not None and v != p, duration / 1000 + 3
                )
                or 0
            )
            _LOGGER.debug(
                "ch%s dimmed for %s ms: %s -> %s (target %s)",
                number,
                duration,
                previous,
                current,
                target,
            )
