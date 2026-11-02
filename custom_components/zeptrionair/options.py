"""Per-channel options (cover travel times, dimmer timing) and the options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector
from zeptrionair_api import Category

from .const import (
    CONF_CHANNELS,
    CONF_DIM_TIME,
    CONF_POSITION_TRACKING,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DEFAULT_DIM_TIME,
    DEFAULT_TRAVEL_TIME,
)


def channel_options(entry: ConfigEntry, number: int) -> dict[str, Any]:
    """Options stored for one channel (empty if none)."""
    channels = entry.options.get(CONF_CHANNELS, {})
    return dict(channels.get(str(number), {}))


def _seconds(minimum: float, maximum: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.5,
            unit_of_measurement="s",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class ZeptrionOptionsFlow(OptionsFlow):
    """Choose a channel, then edit its settings."""

    def __init__(self) -> None:
        self._channel: int | None = None

    def _configurable(self) -> dict[int, tuple[str, Category]]:
        coordinator = self.config_entry.runtime_data
        return {
            channel.number: (channel.name, channel.category)
            for channel in coordinator.used_channels
            if channel.category in (Category.BLIND, Category.AWNING, Category.DIMMER)
        }

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if getattr(self.config_entry, "runtime_data", None) is None:
            return self.async_abort(reason="not_loaded")
        channels = self._configurable()
        if not channels:
            return self.async_abort(reason="nothing_to_configure")
        if user_input is not None:
            self._channel = int(user_input["channel"])
            return await self.async_step_channel()
        choices = [
            selector.SelectOptionDict(value=str(number), label=f"{name} (ch{number})")
            for number, (name, _category) in sorted(channels.items())
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("channel"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=choices)
                    )
                }
            ),
        )

    async def async_step_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._channel is not None
        name, category = self._configurable()[self._channel]
        current = channel_options(self.config_entry, self._channel)

        if user_input is not None:
            options = {**self.config_entry.options}
            channels = {**options.get(CONF_CHANNELS, {})}
            channels[str(self._channel)] = user_input
            options[CONF_CHANNELS] = channels
            return self.async_create_entry(data=options)

        if category is Category.DIMMER:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_DIM_TIME, default=current.get(CONF_DIM_TIME, DEFAULT_DIM_TIME)
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=500,
                            max=32000,
                            step=100,
                            unit_of_measurement="ms",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            )
            step_id = "dimmer"
        else:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_POSITION_TRACKING,
                        default=current.get(CONF_POSITION_TRACKING, False),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_TRAVEL_TIME_UP,
                        default=current.get(CONF_TRAVEL_TIME_UP, DEFAULT_TRAVEL_TIME),
                    ): _seconds(1, 300),
                    vol.Required(
                        CONF_TRAVEL_TIME_DOWN,
                        default=current.get(CONF_TRAVEL_TIME_DOWN, DEFAULT_TRAVEL_TIME),
                    ): _seconds(1, 300),
                }
            )
            step_id = "cover"
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            description_placeholders={"channel": f"{name} (ch{self._channel})"},
        )

    async def async_step_cover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_channel(user_input)

    async def async_step_dimmer(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_channel(user_input)
