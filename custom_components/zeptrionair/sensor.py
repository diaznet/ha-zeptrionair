"""Diagnostic sensors: Wi-Fi signal, Smartfront sensors, connection statistics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator, ZeptrionData
from .entity import ZeptrionHubEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZeptrionSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ZeptrionData], float | int | None] = lambda _data: None
    #: For values kept by the coordinator itself (connection statistics).
    stats_fn: Callable[[ZeptrionCoordinator], int] | None = None
    always: bool = False  # created for every zApp


SENSORS: tuple[ZeptrionSensorDescription, ...] = (
    ZeptrionSensorDescription(
        key="rssi",
        translation_key="rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.rssi,
    ),
    ZeptrionSensorDescription(
        key="device_temperature",
        translation_key="device_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.sensors.temperature if data.sensors else None,
    ),
    ZeptrionSensorDescription(
        key="illuminance",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.sensors.illuminance if data.sensors else None,
    ),
    ZeptrionSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.sensors.humidity if data.sensors else None,
    ),
    ZeptrionSensorDescription(
        key="connections",
        translation_key="connections",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        stats_fn=lambda coordinator: coordinator.stats.connections,
        always=True,
    ),
    ZeptrionSensorDescription(
        key="short_outages",
        translation_key="short_outages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        stats_fn=lambda coordinator: coordinator.stats.short_outages,
        always=True,
    ),
    ZeptrionSensorDescription(
        key="long_outages",
        translation_key="long_outages",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        stats_fn=lambda coordinator: coordinator.stats.long_outages,
        always=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZeptrionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    # Sensors other than RSSI only exist for values the Smartfront actually reports.
    async_add_entities(
        ZeptrionSensor(coordinator, description)
        for description in SENSORS
        if description.key == "rssi" or description.always or description.value_fn(data) is not None
    )


class ZeptrionSensor(ZeptrionHubEntity, SensorEntity):
    entity_description: ZeptrionSensorDescription

    def __init__(
        self, coordinator: ZeptrionCoordinator, description: ZeptrionSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | None:
        if self.entity_description.stats_fn is not None:
            return self.entity_description.stats_fn(self.coordinator)
        return self.entity_description.value_fn(self.coordinator.data)
