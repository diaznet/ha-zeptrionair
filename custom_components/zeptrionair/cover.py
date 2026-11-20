"""Covers: blinds/shades (category 5) and awnings (category 6).

The zApp reports only whether the motor runs (value 100) or not (0). Everything else is
inferred here (see docs/protocol.md section 5.4 of zeptrionair-api for the measurements):

- **Direction:** from the command Home Assistant sent, a decoded wall-key press, a remembered
  scene, or the end stop the cover is at (it can only move away from it).
- **End stops:** a run nobody stopped (no stop command, key press or release, timed command,
  scene) ended at an end stop, because the zApp switches the motor off there.
- **Position** (with travel times): estimated from the motor time. Travel times are typed in,
  learned from full runs between the end stops, or measured with *Calibrate*.
- **Slats** (with a slat tilt time): the first part of a run after a change of direction turns
  the slats instead of moving the blind.
- **Scenes:** the zApp stores the end stop a blind came from plus the net time from there, and a
  recall from elsewhere is two runs: to that end stop, then back. Scenes stored through Home
  Assistant are remembered, so their recall is followed exactly; others are followed with the
  end-stop and duration rules.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.translation import async_get_translations
from zeptrionair_api import Category, Channel, scene_command, timed_command
from zeptrionair_api.const import TIMED_MAX_MS, TIMED_MIN_MS

from .const import (
    CONF_CHANNELS,
    CONF_LEARN_TRAVEL_TIMES,
    CONF_LEARNED_DOWN,
    CONF_LEARNED_UP,
    CONF_POSITION_TRACKING,
    CONF_STEP_DURATION,
    CONF_TILT_TIME,
    CONF_TRAVEL_TIME_DOWN,
    CONF_TRAVEL_TIME_UP,
    DEFAULT_STEP_DURATION,
    DEFAULT_TRAVEL_TIME,
    DOMAIN,
    END_TOLERANCE,
    HOLD_RELEASE_WINDOW,
    LEARN_MAX,
    LEARN_MIN,
)
from .coordinator import Direction, ZeptrionConfigEntry, ZeptrionCoordinator
from .entity import ZeptrionMainChannelEntity
from .options import channel_options

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
_END_SNAP = 0.95  # with travel times: a run of >= 95 % of the travel time reached the end stop
_TICK = timedelta(seconds=1)
_ATTR_POSITION = "current_position"  # restored from older versions' state
_START_TIMEOUT = 3.0  # a command that doesn't start the motor within this time did nothing
_RUN_TIMEOUT = 360.0


def _tolerance(needed: float) -> float:
    """How far a run to an end stop may differ from the computed time (motor overrun, latency).

    At most END_TOLERANCE, and less for short runs so they stay distinguishable.
    """
    return min(END_TOLERANCE, 0.1 * needed + 0.2)


def _opposite(direction: Direction) -> Direction:
    return "down" if direction == "up" else "up"


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


@dataclass(frozen=True)
class RunResult:
    """How a motor run ended."""

    direction: Direction | None
    duration: float
    at_end_stop: bool
    stopped_by_someone: bool


class SequenceAbortedError(Exception):
    """A calibration or scene sequence was interrupted (stop, key press, other run)."""


class _CoverExtraData(ExtraStoredData):
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        return self.data


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
        self._position: float | None = None  # 0 = closed, 100 = open
        self._tilt: float | None = None  # 0 = slats closed, 100 = open
        self._closed: bool | None = None  # open/closed when the position is unknown
        self._at_end: Direction | None = None  # the end stop the cover is at right now
        self._last_end: Direction | None = None  # the end stop it last left / reached
        self._last_motion: Direction | None = None
        self._scenes: dict[int, tuple[Direction, float]] = {}  # stored through HA
        self._scene_plan: list[tuple[Direction, float | None]] = []
        self._scene_target: float | None = None
        self._tilt_target: float | None = None  # angle a timed slat run is turning to

        self._moving = False
        self._direction: Direction | None = None
        self._direction_inferred = False
        self._partial_run = False
        self._started_at = 0.0
        self._start_position: float | None = None
        self._position_before_run: float | None = None
        self._start_tilt: float | None = None
        self._started_from_end: Direction | None = None
        self._start_waiters: list[asyncio.Future[None]] = []
        self._run_waiters: list[asyncio.Future[RunResult]] = []
        self._ticker: CALLBACK_TYPE | None = None
        self._stop_timer: CALLBACK_TYPE | None = None
        self._sequence: asyncio.Task[None] | None = None

    # --------------------------------------------------------------- options

    @property
    def _options(self) -> dict[str, Any]:
        return channel_options(self.coordinator.config_entry, self.channel.number)

    def travel_time(self, direction: Direction) -> float:
        key = CONF_TRAVEL_TIME_UP if direction == "up" else CONF_TRAVEL_TIME_DOWN
        return float(self._options.get(key, DEFAULT_TRAVEL_TIME))

    @property
    def tracking(self) -> bool:
        """Position estimation: on if enabled, or once both travel times were measured."""
        options = self._options
        if CONF_POSITION_TRACKING in options:
            return bool(options[CONF_POSITION_TRACKING])
        return bool(options.get(CONF_LEARNED_UP) and options.get(CONF_LEARNED_DOWN))

    @property
    def tilt_time(self) -> float:
        return float(self._options.get(CONF_TILT_TIME, 0) or 0)

    @property
    def step_duration(self) -> int:
        return int(self._options.get(CONF_STEP_DURATION, DEFAULT_STEP_DURATION))

    @property
    def supported_features(self) -> CoverEntityFeature:
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        if self.tracking:
            features |= CoverEntityFeature.SET_POSITION
        if self.tilt_time > 0:
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.STOP_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
        return features

    @property
    def assumed_state(self) -> bool:
        return not self.tracking

    # ------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in (STATE_OPEN, STATE_CLOSED):
                self._closed = last.state == STATE_CLOSED
            position = last.attributes.get(_ATTR_POSITION)
            if isinstance(position, (int, float)):
                self._position = float(position)
        if (extra := await self.async_get_last_extra_data()) is not None:
            self._restore(extra.as_dict())
        if self.value == 100:  # moving at startup: direction unknown
            self._moving = True
            self._direction = None
            self._started_at = time.monotonic()
            self._position = None
            self._closed = None
            self._at_end = None
        self.async_on_remove(self._cleanup)

    def _restore(self, data: dict[str, Any]) -> None:
        def direction(value: Any) -> Direction | None:
            return value if value in ("up", "down") else None

        if isinstance(data.get("position"), (int, float)):
            self._position = float(data["position"])
        if isinstance(data.get("tilt"), (int, float)):
            self._tilt = float(data["tilt"])
        self._at_end = direction(data.get("at_end"))
        self._last_end = direction(data.get("last_end"))
        self._last_motion = direction(data.get("last_motion"))
        for key, value in (data.get("scenes") or {}).items():
            if str(key).isdigit() and isinstance(value, list) and len(value) == 2:
                end = direction(value[0])
                if end is not None and isinstance(value[1], (int, float)):
                    self._scenes[int(key)] = (end, float(value[1]))

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return _CoverExtraData(
            {
                "position": self._position,
                "tilt": self._tilt,
                "at_end": self._at_end,
                "last_end": self._last_end,
                "last_motion": self._last_motion,
                "scenes": {str(k): [v[0], v[1]] for k, v in self._scenes.items()},
            }
        )

    @callback
    def _cleanup(self) -> None:
        if self._ticker is not None:
            self._ticker()
            self._ticker = None
        self._cancel_stop_timer()
        if self._sequence is not None:
            self._sequence.cancel()
        for future in [*self._start_waiters, *self._run_waiters]:
            if not future.done():
                future.cancel()

    # -------------------------------------------------------------- tracking

    @callback
    def _handle_coordinator_update(self) -> None:
        running = self.value == 100
        if running and not self._moving:
            self._on_start()
        elif not running and self._moving:
            self._on_stop()
        super()._handle_coordinator_update()

    def _tilt_now(self) -> float | None:
        """The slat angle before a run: known, or the end of the last motion."""
        if self.tilt_time <= 0:
            return None
        if self._tilt is not None:
            return self._tilt
        if self._last_motion is not None:
            return 100.0 if self._last_motion == "up" else 0.0
        return None

    def _tilt_phase(self, direction: Direction, start_tilt: float | None) -> float:
        """Seconds of a run in ``direction`` spent turning the slats."""
        if self.tilt_time <= 0:
            return 0.0
        target = 100.0 if direction == "up" else 0.0
        start = start_tilt if start_tilt is not None else 50.0
        return abs(target - start) / 100 * self.tilt_time

    def _on_start(self) -> None:
        number = self.channel.number
        direction = self.coordinator.consume_direction(number)
        partial = self.coordinator.consume_partial_run(number)
        inferred = False
        if self._scene_plan:
            planned, net = self._scene_plan.pop(0)
            direction, partial = planned, net is not None
        if direction is None and self._at_end is not None:
            direction, inferred = _opposite(self._at_end), True  # it can only move away
        self._position_before_run = self._position
        self._started_from_end = self._at_end
        if self._at_end is not None:
            self._last_end = self._at_end
        self._at_end = None
        self._moving = True
        self._direction = direction
        self._direction_inferred = inferred
        self._partial_run = partial
        self._started_at = time.monotonic()
        self._start_tilt = self._tilt_now()
        self._start_position = self._position if direction is not None else None
        if direction is None:  # moved by something we can't interpret (yet)
            self._position = None
            self._closed = None
            self._tilt = None
        if (self.tracking or self.tilt_time > 0) and self._ticker is None:
            self._ticker = async_track_time_interval(self.hass, self._tick, _TICK)
        for future in self._start_waiters:
            if not future.done():
                future.set_result(None)
        self._start_waiters.clear()

    def _time_to_end(
        self, direction: Direction, position: float, start_tilt: float | None
    ) -> float:
        distance = (100.0 - position) if direction == "up" else position
        return self._tilt_phase(direction, start_tilt) + distance / 100 * self.travel_time(
            direction
        )

    def _on_stop(self) -> None:
        number = self.channel.number
        duration = time.monotonic() - self._started_at
        by_someone = (
            self._partial_run
            or self.coordinator.recent_stop(number)
            or self.coordinator.recent_release(number, HOLD_RELEASE_WINDOW)
        )
        direction = self._direction
        before = self._position_before_run
        tracking = self.tracking

        # A run of unknown direction from a known position: recognise a run to an end stop by
        # its duration (e.g. the first half of a scene recalled on the wall).
        if direction is None and not by_someone and tracking and before is not None:
            errors = sorted(
                (abs(duration - self._time_to_end(d, before, self._start_tilt)), d)
                for d in ("up", "down")
            )
            (best_error, best), (other_error, _) = errors
            # The closest end stop, if it fits and is clearly closer than the other one.
            if best_error <= END_TOLERANCE and other_error - best_error >= 0.5:
                direction = best  # type: ignore[assignment]
                self._start_position = before

        position = self._live_position(direction)
        tilt = self._live_tilt(direction)
        at_end = direction is not None and not by_someone
        if at_end and self._direction_inferred and tracking and self._start_position is not None:
            # Inferred directions (from an end stop) must also last long enough.
            needed = self._time_to_end(direction, self._start_position, self._start_tilt)
            at_end = duration >= needed - _tolerance(needed)
        elif at_end and self._direction_inferred and not tracking:
            at_end = False  # can't tell how far it went
        full_run = direction is not None and duration >= _END_SNAP * self.travel_time(
            direction
        ) + self._tilt_phase(direction, self._start_tilt)
        if full_run and tracking and not by_someone:
            at_end = True

        if direction is not None:
            self._last_motion = direction
            if at_end:
                position = 100.0 if direction == "up" else 0.0
                tilt = 100.0 if direction == "up" else 0.0
                self._closed = direction == "down"
                self._at_end = direction
                self._last_end = direction
                self._learn(direction, duration)
            elif self._direction_inferred and direction == "down" and not tracking:
                self._closed = None  # moved down from the top, unknown how far
            else:
                self._closed = False  # stopped somewhere between the end stops
        if self._scene_target is not None and not self._scene_plan:
            if not by_someone or self._partial_run:  # the planned last run ended normally
                position, self._at_end = self._scene_target, None
                self._closed = self._scene_target <= 0
            self._scene_target = None
        if by_someone and not self._partial_run:
            self._scene_plan.clear()  # someone interrupted a scene recall
            self._scene_target = None

        if self._tilt_target is not None:
            # A timed slat run that nobody stopped reached its angle. The pushes of short runs
            # arrive with some delay, so their measured duration is too short to rely on.
            if self._partial_run and not self.coordinator.recent_stop(number):
                tilt = self._tilt_target
                if self._position_before_run is not None:
                    position = self._position_before_run  # only the slats turned
            self._tilt_target = None
        self._position = position
        self._tilt = tilt if self.tilt_time > 0 else None
        self._moving = False
        self._direction = None
        self._direction_inferred = False
        self._partial_run = False
        if self._ticker is not None:
            self._ticker()
            self._ticker = None
        result = RunResult(direction, duration, at_end, by_someone)
        for future in self._run_waiters:
            if not future.done():
                future.set_result(result)
        self._run_waiters.clear()

    def _learn(self, direction: Direction, duration: float) -> None:
        """A full run from one end stop to the other gives the travel time (option)."""
        if self._started_from_end != _opposite(direction) or self._partial_run:
            return
        if not self._options.get(CONF_LEARN_TRAVEL_TIMES, True):
            return
        if not LEARN_MIN <= duration <= LEARN_MAX:
            return
        duration -= self._tilt_phase(direction, self._start_tilt)
        self._store_travel_times({direction: duration})

    def _store_travel_times(self, times: dict[Direction, float], *, enable: bool = False) -> None:
        entry = self.coordinator.config_entry
        channels = {**entry.options.get(CONF_CHANNELS, {})}
        options = dict(channels.get(str(self.channel.number), {}))
        changed = False
        for direction, seconds in times.items():
            key = CONF_TRAVEL_TIME_UP if direction == "up" else CONF_TRAVEL_TIME_DOWN
            flag = CONF_LEARNED_UP if direction == "up" else CONF_LEARNED_DOWN
            seconds = round(seconds, 1)
            if options.get(key) != seconds or not options.get(flag):
                options[key], options[flag] = seconds, True
                changed = True
        if enable and options.get(CONF_POSITION_TRACKING) is not True:
            options[CONF_POSITION_TRACKING] = True
            changed = True
        if changed:
            _LOGGER.debug("%s: travel times %s", self.entity_id, times)
            channels[str(self.channel.number)] = options
            self.hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_CHANNELS: channels}
            )

    @callback
    def _tick(self, _now: Any) -> None:
        self.async_write_ha_state()

    def _elapsed(self) -> float:
        return time.monotonic() - self._started_at

    def _live_position(self, direction: Direction | None = None) -> float | None:
        direction = direction or self._direction
        if not self._moving or direction is None:
            return self._position
        if self._start_position is None:
            return None
        moved = max(0.0, self._elapsed() - self._tilt_phase(direction, self._start_tilt))
        change = moved / self.travel_time(direction) * 100
        sign = 1 if direction == "up" else -1
        return min(100.0, max(0.0, self._start_position + sign * change))

    def _live_tilt(self, direction: Direction | None = None) -> float | None:
        if self.tilt_time <= 0:
            return None
        direction = direction or self._direction
        if not self._moving or direction is None:
            return self._tilt
        start = self._start_tilt if self._start_tilt is not None else 50.0
        turned = min(self._elapsed(), self._tilt_phase(direction, start)) / self.tilt_time * 100
        sign = 1 if direction == "up" else -1
        return min(100.0, max(0.0, start + sign * turned))

    @property
    def current_cover_position(self) -> int | None:
        if not self.tracking:
            return None
        position = self._live_position()
        return None if position is None else round(position)

    @property
    def current_cover_tilt_position(self) -> int | None:
        tilt = self._live_tilt()
        return None if tilt is None else round(tilt)

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
        attributes: dict[str, Any] = {}
        for number, (end, seconds) in sorted(self._scenes.items()):
            attributes[f"scene_{number}"] = f"{end} + {seconds:.1f} s"
        return attributes or None

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

    async def _move_seconds(self, direction: Direction, seconds: float) -> None:
        milliseconds = max(TIMED_MIN_MS, round(seconds * 1000))
        action = "move_open" if direction == "up" else "move_close"
        self._cancel_stop_timer()
        if milliseconds <= TIMED_MAX_MS:
            await self._send(timed_command(action, milliseconds), direction, partial=True)
        else:  # longer than the device's timed command allows: stop it ourselves
            await self._send(action, direction)
            self._stop_timer = async_call_later(self.hass, seconds, self._timed_stop)

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
        tilt = self._tilt_phase(direction, self._tilt_now())
        await self._move_seconds(direction, tilt + abs(delta) / 100 * self.travel_time(direction))

    # Slats: the first part of a run after a change of direction turns them.

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        await self._tilt_to(100.0)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        await self._tilt_to(0.0)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        await self.async_stop_cover()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        await self._tilt_to(float(kwargs[ATTR_TILT_POSITION]))

    async def _tilt_to(self, target: float) -> None:
        current = self._tilt_now()
        if current is None:  # unknown angle: turn fully, then the rest is exact
            current = 0.0 if target >= 50 else 100.0
        delta = target - current
        seconds = abs(delta) / 100 * self.tilt_time
        if seconds * 1000 < TIMED_MIN_MS:
            return
        await self._move_seconds("up" if delta > 0 else "down", seconds)
        self._tilt_target = target

    @callback
    def _cancel_stop_timer(self) -> None:
        if self._stop_timer is not None:
            self._stop_timer()
            self._stop_timer = None

    async def _timed_stop(self, _now: Any) -> None:
        self._stop_timer = None
        self.coordinator.note_stop(self.channel.number)
        await self._send("stop", None)

    # ---------------------------------------------------------------- scenes

    def _scene_from_here(self) -> tuple[Direction, float] | None:
        """The scene the zApp stores now: (end stop it came from, net seconds from there)."""
        if self._position is None or self._last_end is None or self._moving:
            return None
        away = _opposite(self._last_end)
        distance = (100.0 - self._position) if self._last_end == "up" else self._position
        return self._last_end, distance / 100 * self.travel_time(away)

    async def async_store_scene(self, scene: int) -> None:
        """Store a scene. Like Feller recommends, a blind that came from the bottom is first
        driven to the top and back (needs a known position), so the scene ends with a run down.
        """
        if self._moving:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="cover_moving")
        if self.tracking and self._last_end == "down" and self._position not in (None, 0.0):
            self._start_sequence(self._store_from_top(scene))
            return
        await self.send_command(scene_command("store", scene))
        self.scene_stored(scene)

    async def _store_from_top(self, scene: int) -> None:
        target = self._position
        assert target is not None
        await self._notify("scene_store_started", scene=str(scene))
        try:
            result = await self._run_and_wait("open", "up")
            if result is not None and not result.at_end_stop:
                raise SequenceAbortedError
            if target < 100:
                down = await self._run_and_wait_seconds("down", 100.0 - target)
                if down is None or down.direction != "down":
                    raise SequenceAbortedError
            await self.send_command(scene_command("store", scene))
            self.scene_stored(scene)
            await self._notify("scene_stored", scene=str(scene))
        except SequenceAbortedError:
            await self._notify("sequence_aborted")

    def scene_stored(self, scene: int) -> None:
        stored = self._scene_from_here()
        if stored is not None:
            self._scenes[scene] = stored
        else:
            self._scenes.pop(scene, None)
        self.async_write_ha_state()

    def scene_recalling(self, scene: int) -> None:
        number = self.channel.number
        stored = self._scenes.get(scene)
        if stored is None or self._position is None or not self.tracking:
            self.coordinator.note_partial_run(number)  # unknown scene: follow by the rules
            return
        end, seconds = stored
        away = _opposite(end)
        if self._moving:
            self.coordinator.note_stop(number)  # the zApp stops a running motor first
        plan: list[tuple[Direction, float | None]] = []
        if self._at_end != end:
            plan.append((end, None))
        plan.append((away, seconds))
        self._scene_plan = plan
        change = seconds / self.travel_time(away) * 100
        self._scene_target = (100.0 - change) if end == "up" else change
        self._scene_target = min(100.0, max(0.0, self._scene_target))

    # ----------------------------------------------------------- calibration

    def _start_sequence(self, coro: Any) -> None:
        if self._sequence is not None and not self._sequence.done():
            coro.close()
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="cover_busy")
        self._sequence = self.hass.async_create_background_task(
            coro, f"{DOMAIN} {self.entity_id} sequence"
        )

    async def async_calibrate(self) -> None:
        """Measure both travel times: fully up, down, up, then back to the previous position."""
        if self._moving:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="cover_moving")
        self._start_sequence(self._calibrate())

    async def _calibrate(self) -> None:
        previous = self._position if self.tracking else None
        await self._notify("calibration_started")
        try:
            first = await self._run_and_wait("open", "up")
            if first is not None and not first.at_end_stop:
                raise SequenceAbortedError
            down = await self._run_and_wait("close", "down")
            if down is None or not down.at_end_stop:
                raise SequenceAbortedError
            up = await self._run_and_wait("open", "up")
            if up is None or not up.at_end_stop:
                raise SequenceAbortedError
            tilt_down = self._tilt_phase("down", 100.0)
            tilt_up = self._tilt_phase("up", 0.0)
            times: dict[Direction, float] = {
                "down": down.duration - tilt_down,
                "up": up.duration - tilt_up,
            }
            self._store_travel_times(times, enable=True)
            if previous is not None and previous < 99:
                await self._run_and_wait_seconds("down", 100.0 - previous)
            await self._notify(
                "calibration_done", up=f"{times['up']:.1f}", down=f"{times['down']:.1f}"
            )
        except SequenceAbortedError:
            await self._notify("sequence_aborted")

    async def _run_and_wait(self, command: str, direction: Direction) -> RunResult | None:
        """Send a command and wait for the run it starts. ``None``: the motor didn't start
        (e.g. ``open`` on a blind that is already at the top)."""
        loop = asyncio.get_running_loop()
        started: asyncio.Future[None] = loop.create_future()
        finished: asyncio.Future[RunResult] = loop.create_future()
        self._start_waiters.append(started)
        self._run_waiters.append(finished)
        await self._send(command, direction)
        try:
            await asyncio.wait_for(asyncio.shield(started), _START_TIMEOUT)
        except TimeoutError:
            self._run_waiters.remove(finished)
            return None
        result = await asyncio.wait_for(finished, _RUN_TIMEOUT)
        if result.stopped_by_someone or result.direction != direction:
            raise SequenceAbortedError
        return result

    async def _run_and_wait_seconds(self, direction: Direction, percent: float) -> RunResult | None:
        """Move ``percent`` of the travel in ``direction`` (from a known position) and wait."""
        seconds = self._tilt_phase(direction, self._tilt_now()) + percent / 100 * (
            self.travel_time(direction)
        )
        loop = asyncio.get_running_loop()
        finished: asyncio.Future[RunResult] = loop.create_future()
        self._run_waiters.append(finished)
        await self._move_seconds(direction, seconds)
        return await asyncio.wait_for(finished, _RUN_TIMEOUT)

    async def _notify(self, key: str, **placeholders: str) -> None:
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "exceptions", {DOMAIN}
        )
        name = self.name if isinstance(self.name, str) else None
        placeholders["name"] = name or (self.device_entry.name if self.device_entry else "")
        template = translations.get(f"component.{DOMAIN}.exceptions.{key}.message", key)
        try:
            message = template.format(**placeholders)
        except (KeyError, IndexError):
            message = template
        persistent_notification.async_create(
            self.hass,
            message,
            title="Feller zeptrionAir",
            notification_id=f"{DOMAIN}_{self.entity_id}",
        )
