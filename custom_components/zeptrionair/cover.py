"""Covers: blinds/shades (category 5) and awnings (category 6).

The device reports only whether the motor runs (value 100) or not (0). Direction comes from the
last command sent by Home Assistant or from a decoded wall-key press.

End stops: a run that ends without anyone stopping it (no stop command or key press, no timed
command, no scene recall) reached an end stop, because the zApp switches the motor off there. So
the cover is shown open or closed even without travel times. With position tracking enabled in
the options, the position is also estimated from the configured travel times.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from zeptrionair_api import Category, Channel, timed_command
from zeptrionair_api.const import TIMED_MAX_MS, TIMED_MIN_MS

from .const import (
    CONF_POSITION_TRACKING,
    CONF_STEP_DURATION,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DEFAULT_STEP_DURATION,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
)
from .coordinator import Direction, ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionMainChannelEntity
from .options import channel_options

PARALLEL_UPDATES = 0
_END_SNAP = 0.95  # with travel times: a run of >= 95 % of the travel time ends at the end stop
_TICK = timedelta(seconds=1)
_ATTR_POSITION = "current_position"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZeptrionCover(coordinator, channel)
        for channel in coordinator.used_channels
        if channel.category is not None and channel.category.is_cover
    )


class ZeptrionCover(ZeptrionMainChannelEntity, CoverEntity, RestoreEntity):
    """A cover channel. The entity is the main feature of its channel device."""

    _attr_name = None

    def __init__(self, coordinator: ZeptrionCoordinator, channel: Channel) -> None:
        super().__init__(coordinator, channel)
        self._attr_device_class = (
            CoverDeviceClass.AWNING
            if channel.category is Category.AWNING
            else CoverDeviceClass.SHADE
        )
        options = channel_options(coordinator.config_entry, channel.number)
        self._tracking = bool(options.get(CONF_POSITION_TRACKING, False))
        self._travel = {
            "up": float(options.get(CONF_TRAVEL_TIME_UP, DEFAULT_TRAVEL_TIME)),
            "down": float(options.get(CONF_TRAVEL_TIME_DOWN, DEFAULT_TRAVEL_TIME)),
        }
        self.step_duration = int(options.get(CONF_STEP_DURATION, DEFAULT_STEP_DURATION))
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if self._tracking:
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features
        self._attr_assumed_state = not self._tracking

        self._position: float | None = None  # 0 = closed, 100 = open (with tracking)
        self._closed: bool | None = None  # open/closed state (without tracking)
        self._moving = False
        self._direction: Direction | None = None
        self._partial_run = False  # this run will end before an end stop (timed command)
        self._started_at = 0.0
        self._start_position: float | None = None
        self._ticker: CALLBACK_TYPE | None = None
        self._stop_timer: CALLBACK_TYPE | None = None

    # ------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in (STATE_OPEN, STATE_CLOSED):
                self._closed = last.state == STATE_CLOSED
            position = last.attributes.get(_ATTR_POSITION)
            if self._tracking and isinstance(position, (int, float)):
                self._position = float(position)
        self._moving = self.value == 100
        if self._moving:  # moving at startup: direction unknown
            self._direction = None
            self._position = None
            self._closed = None
        self.async_on_remove(self._cancel_timers)

    @callback
    def _cancel_timers(self) -> None:
        if self._ticker is not None:
            self._ticker()
            self._ticker = None
        self._cancel_stop_timer()

    # ----------------------------------------------------------------- state

    @callback
    def _handle_coordinator_update(self) -> None:
        running = self.value == 100
        if running and not self._moving:
            self._on_start()
        elif not running and self._moving:
            self._on_stop()
        super()._handle_coordinator_update()

    def _on_start(self) -> None:
        number = self.channel.number
        self._moving = True
        self._direction = self.coordinator.consume_direction(number)
        self._partial_run = self.coordinator.consume_partial_run(number)
        self._started_at = time.monotonic()
        self._start_position = self._position if self._direction is not None else None
        if self._direction is None:  # moved by something we can't interpret
            self._position = None
            self._closed = None
        if self._tracking and self._ticker is None:
            self._ticker = async_track_time_interval(self.hass, self._tick, _TICK)

    def _on_stop(self) -> None:
        number = self.channel.number
        stopped_by_someone = self._partial_run or self.coordinator.recent_stop(number)
        at_end_stop = self._direction is not None and not stopped_by_someone
        position = self._live_position()
        if self._direction is not None:
            elapsed = time.monotonic() - self._started_at
            if self._tracking and elapsed >= _END_SNAP * self._travel[self._direction]:
                at_end_stop = True
            if at_end_stop:
                position = 100.0 if self._direction == "up" else 0.0
                self._closed = self._direction == "down"
            else:
                self._closed = False  # stopped somewhere between the end stops
        self._position = position
        self._moving = False
        self._direction = None
        self._partial_run = False
        if self._ticker is not None:
            self._ticker()
            self._ticker = None

    @callback
    def _tick(self, _now: Any) -> None:
        self.async_write_ha_state()

    def _live_position(self) -> float | None:
        if not self._moving or self._direction is None:
            return self._position
        if self._start_position is None:
            return None
        elapsed = time.monotonic() - self._started_at
        change = elapsed / self._travel[self._direction] * 100
        sign = 1 if self._direction == "up" else -1
        return min(100.0, max(0.0, self._start_position + sign * change))

    @property
    def current_cover_position(self) -> int | None:
        if not self._tracking:
            return None
        position = self._live_position()
        return None if position is None else round(position)

    @property
    def is_closed(self) -> bool | None:
        position = self.current_cover_position
        if position is not None:
            return position == 0
        return self._closed

    @property
    def is_opening(self) -> bool:
        return self._moving and self._direction == "up"

    @property
    def is_closing(self) -> bool:
        return self._moving and self._direction == "down"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self._tracking or self._position is None:
            return None
        return {_ATTR_POSITION: round(self._position, 1)}

    # -------------------------------------------------------------- commands

    async def _send(
        self, command: str, direction: Direction | None, *, partial: bool = False
    ) -> None:
        number = self.channel.number
        if direction is not None:
            self.coordinator.note_direction(number, direction)
        if partial:
            self.coordinator.note_partial_run(number)
        await self.send_command(command)

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._cancel_stop_timer()
        await self._send("open", "up")

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._cancel_stop_timer()
        await self._send("close", "down")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._cancel_stop_timer()
        self.coordinator.note_stop(self.channel.number)
        await self._send("stop", None)

    async def async_move_step(self, direction: Direction, duration: int | None = None) -> None:
        """Move for a short time (``duration`` ms, default: the step option) in ``direction``."""
        milliseconds = max(TIMED_MIN_MS, min(TIMED_MAX_MS, int(duration or self.step_duration)))
        action = "move_open" if direction == "up" else "move_close"
        self._cancel_stop_timer()
        await self._send(timed_command(action, milliseconds), direction, partial=True)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = float(kwargs[ATTR_POSITION])
        if target >= 100:
            await self.async_open_cover()
            return
        if target <= 0:
            await self.async_close_cover()
            return
        current = self._live_position()
        if current is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="position_unknown")
        if self._moving:
            await self.async_stop_cover()
            current = self._live_position() or current
        delta = target - current
        if abs(delta) < 1:
            return
        direction: Direction = "up" if delta > 0 else "down"
        seconds = abs(delta) / 100 * self._travel[direction]
        milliseconds = max(TIMED_MIN_MS, round(seconds * 1000))
        action = "move_open" if direction == "up" else "move_close"
        self._cancel_stop_timer()
        if milliseconds <= TIMED_MAX_MS:
            await self._send(timed_command(action, milliseconds), direction, partial=True)
        else:  # longer than the device's timed command allows: stop it ourselves
            await self._send(action, direction)
            self._stop_timer = async_call_later(self.hass, seconds, self._timed_stop)

    @callback
    def _cancel_stop_timer(self) -> None:
        if self._stop_timer is not None:
            self._stop_timer()
            self._stop_timer = None

    async def _timed_stop(self, _now: Any) -> None:
        self._stop_timer = None
        self.coordinator.note_stop(self.channel.number)
        await self._send("stop", None)

    # A scene run goes to the end stop it was stored from and then back for a time, so its end
    # is not an end stop and its direction is unknown to us.

    def scene_recalling(self, scene: int) -> None:
        self.coordinator.note_partial_run(self.channel.number)
