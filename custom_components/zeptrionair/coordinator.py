"""Coordinator: initial load, push events from the device, safety polling."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from zeptrionair_api import (
    Capabilities,
    Channel,
    ChannelUpdate,
    ConnectionEvent,
    DeviceInfo,
    KeyEvent,
    SensorValues,
    SmartfrontInfo,
    ZeptrionDevice,
    ZeptrionError,
)

from .const import (
    DIRECTION_VALID_FOR,
    DOMAIN,
    FALLBACK_POLL_INTERVAL,
    PUSH_POLL_INTERVAL,
    UNAVAILABLE_GRACE,
)

_LOGGER = logging.getLogger(__name__)

type ZeptrionConfigEntry = ConfigEntry[ZeptrionCoordinator]
Direction = Literal["up", "down"]


@dataclass(frozen=True)
class ZeptrionData:
    """Current state of one zApp device."""

    values: dict[int, int | None]
    rssi: int | None = None
    sensors: SensorValues | None = None
    connected: bool = True


@dataclass
class _DirectionHint:
    direction: Direction
    at: float = field(default_factory=time.monotonic)


class ZeptrionCoordinator(DataUpdateCoordinator[ZeptrionData]):
    """Keeps one zApp device's state up to date (push first, polling as a safety net)."""

    config_entry: ZeptrionConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ZeptrionConfigEntry, device: ZeptrionDevice
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.host}",
            update_interval=PUSH_POLL_INTERVAL,
            always_update=False,
        )
        self.device = device
        self.info: DeviceInfo
        self.channels: list[Channel] = []
        self.smartfront: SmartfrontInfo | None = None
        self.capabilities = Capabilities(False, False, False, False)
        self.mac: str | None = None
        self.hub_device_id: str | None = None
        self._key_listeners: list[Callable[[KeyEvent], None]] = []
        self._directions: dict[int, _DirectionHint] = {}
        self._unavailable_timer: CALLBACK_TYPE | None = None
        self._stream_down = False

    # ------------------------------------------------------------------ setup

    async def _async_setup(self) -> None:
        """Load what doesn't change while the device runs."""
        try:
            self.info = await self.device.identify()
            self.channels = await self.device.channels()
            self.smartfront = await self.device.smartfront()
            self.capabilities = await self.device.probe()
            try:
                self.mac = await self.device.mac()
            except ZeptrionError:
                self.mac = None
        except ZeptrionError as err:
            raise UpdateFailed(f"cannot read device information: {err}") from err
        if not self.capabilities.websocket:
            self.update_interval = FALLBACK_POLL_INTERVAL

    async def _async_update_data(self) -> ZeptrionData:
        try:
            values = await self.device.states()
            rssi = await self.device.rssi()
            sensors = await self.device.sensors() if self.capabilities.sensors else None
        except ZeptrionError as err:
            raise UpdateFailed(f"cannot read device state: {err}") from err
        connected = self.data.connected if self.data is not None else True
        return ZeptrionData(values=values, rssi=rssi, sensors=sensors, connected=connected)

    @property
    def used_channels(self) -> list[Channel]:
        return [channel for channel in self.channels if channel.in_use]

    def channel(self, number: int) -> Channel | None:
        for channel in self.channels:
            if channel.number == number:
                return channel
        return None

    # --------------------------------------------------------------- listening

    @callback
    def async_start_listening(self) -> None:
        """Start the background task consuming the device's event stream."""
        self.config_entry.async_create_background_task(
            self.hass, self._listen(), name=f"{DOMAIN} events {self.device.host}"
        )
        self.config_entry.async_on_unload(self._cancel_unavailable_timer)

    async def _listen(self) -> None:
        keys = self.smartfront.keys if self.smartfront else ()
        while True:
            try:
                async for event in self.device.events(keys=keys):
                    self._handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the library reconnects by itself
                _LOGGER.exception("Event stream of %s failed, restarting", self.device.host)
                await asyncio.sleep(30)

    @callback
    def _handle_event(self, event: ChannelUpdate | KeyEvent | ConnectionEvent) -> None:
        if isinstance(event, ChannelUpdate):
            if self.data is None:  # pragma: no cover - first refresh always ran
                return
            values = {**self.data.values, event.channel: event.value}
            self.async_set_updated_data(replace(self.data, values=values, connected=True))
        elif isinstance(event, KeyEvent):
            function = event.function
            if event.pressed and function is not None and function.direction is not None:
                for channel in function.channels:
                    self.note_direction(channel, function.direction)
            for listener in list(self._key_listeners):
                listener(event)
        else:
            self._handle_connection(event)

    @callback
    def _handle_connection(self, event: ConnectionEvent) -> None:
        if event.connected:
            if self._stream_down:
                _LOGGER.info("Event stream of %s is back (%s)", self.device.host, event.transport)
            self._stream_down = False
            self._cancel_unavailable_timer()
            if self.data is not None and not self.data.connected:
                self.async_set_updated_data(replace(self.data, connected=True))
            return
        if not self._stream_down:
            _LOGGER.warning("Lost the event stream of %s: %s", self.device.host, event.error)
        self._stream_down = True
        if self._unavailable_timer is None:
            self._unavailable_timer = async_call_later(
                self.hass, UNAVAILABLE_GRACE, self._mark_unavailable
            )

    @callback
    def _mark_unavailable(self, _now: object) -> None:
        self._unavailable_timer = None
        if self._stream_down and self.data is not None:
            self.async_set_updated_data(replace(self.data, connected=False))

    @callback
    def _cancel_unavailable_timer(self) -> None:
        if self._unavailable_timer is not None:
            self._unavailable_timer()
            self._unavailable_timer = None

    # ------------------------------------------------------------ key presses

    @callback
    def async_add_key_listener(self, listener: Callable[[KeyEvent], None]) -> CALLBACK_TYPE:
        self._key_listeners.append(listener)

        @callback
        def remove() -> None:
            self._key_listeners.remove(listener)

        return remove

    # -------------------------------------------------------------- directions

    @callback
    def note_direction(self, channel: int, direction: Direction) -> None:
        """Remember which way a cover is about to move (from a command or a key press)."""
        self._directions[channel] = _DirectionHint(direction)

    def recent_direction(self, channel: int) -> Direction | None:
        hint = self._directions.get(channel)
        if hint is None or time.monotonic() - hint.at > DIRECTION_VALID_FOR:
            return None
        return hint.direction

    # ---------------------------------------------------------------- helpers

    async def async_wait_for(
        self, channel: int, predicate: Callable[[int | None], bool], timeout: float
    ) -> int | None:
        """Wait until the channel value satisfies ``predicate`` (or the timeout passes)."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[int | None] = loop.create_future()

        @callback
        def check() -> None:
            value = self.data.values.get(channel) if self.data else None
            if not future.done() and predicate(value):
                future.set_result(value)

        remove = self.async_add_listener(check)
        try:
            check()
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError:
            return self.data.values.get(channel) if self.data else None
        finally:
            remove()
