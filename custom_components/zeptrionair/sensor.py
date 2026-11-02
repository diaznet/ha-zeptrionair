"""Diagnostic sensors: Wi-Fi signal and Smartfront sensors."""

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
    value_fn: Callable[[ZeptrionData], float | int | None]


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
        if description.key == "rssi" or description.value_fn(data) is not None
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
        return self.entity_description.value_fn(self.coordinator.data)
