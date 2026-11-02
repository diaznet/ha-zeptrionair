"""The Feller zeptrionAir integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from zeptrionair_api import ZeptrionDevice

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZeptrionConfigEntry, ZeptrionCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.COVER,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ZeptrionConfigEntry) -> bool:
    """Set up a zApp device from a config entry."""
    device = ZeptrionDevice(entry.data[CONF_HOST], session=async_get_clientsession(hass))
    coordinator = ZeptrionCoordinator(hass, entry, device)
    await coordinator.async_config_entry_first_refresh()

    # Register the hub device first so channel devices can be linked to it.
    info = coordinator.info
    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, info.serial)},
        connections={(dr.CONNECTION_NETWORK_MAC, coordinator.mac)} if coordinator.mac else set(),
        manufacturer=MANUFACTURER,
        model=info.type,
        name=f"zApp-{info.serial}",
        sw_version=info.sw_version,
        hw_version=info.hw_version,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
    coordinator.hub_device_id = hub.id

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_listening()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZeptrionConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ZeptrionConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
