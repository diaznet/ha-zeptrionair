"""Config flow: manual host, mDNS (zeroconf) and DHCP discovery, reconfigure."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from zeptrionair_api import DeviceInfo, ZeptrionDevice, ZeptrionError
from zeptrionair_api.discovery import serial_from_name

from .const import DOMAIN
from .options import ZeptrionOptionsFlow

_LOGGER = logging.getLogger(__name__)

HOST_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class CannotConnect(Exception):
    """The device could not be reached or is not a zApp device."""


class ZeptrionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a zApp device."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._serial: str | None = None
        self._info: DeviceInfo | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ZeptrionOptionsFlow:
        return ZeptrionOptionsFlow()

    async def _identify(self, host: str) -> DeviceInfo:
        device = ZeptrionDevice(host, session=async_get_clientsession(self.hass))
        try:
            return await device.identify()
        except ZeptrionError as err:
            _LOGGER.debug("Cannot identify %s: %s", host, err)
            raise CannotConnect from err

    @staticmethod
    def _title(info: DeviceInfo) -> str:
        return f"zApp-{info.serial}"

    # ------------------------------------------------------------ manual setup

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._identify(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.serial, raise_on_progress=False)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(title=self._title(info), data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(HOST_SCHEMA, user_input),
            errors=errors,
        )

    # --------------------------------------------------------------- discovery

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        serial = serial_from_name(discovery_info.name) or serial_from_name(discovery_info.hostname)
        if serial is None:
            return self.async_abort(reason="not_zeptrion")
        return await self._async_discovered(str(discovery_info.ip_address), serial)

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        host = discovery_info.ip
        serial = serial_from_name(discovery_info.hostname)
        if serial is None:
            # Matched via registered_devices: find the entry by MAC and update its address.
            mac = format_mac(discovery_info.macaddress)
            for entry in self._async_current_entries(include_ignore=False):
                coordinator = getattr(entry, "runtime_data", None)
                if (
                    coordinator is not None
                    and coordinator.mac
                    and format_mac(coordinator.mac) == mac
                ):
                    serial = entry.unique_id
                    break
            if serial is None:
                return self.async_abort(reason="not_zeptrion")
        return await self._async_discovered(host, serial)

    async def _async_discovered(self, host: str, serial: str) -> ConfigFlowResult:
        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        try:
            info = await self._identify(host)
        except CannotConnect:
            return self.async_abort(reason="cannot_connect")
        if info.serial != serial:
            return self.async_abort(reason="not_zeptrion")
        self._host = host
        self._info = info
        self.context["title_placeholders"] = {"name": self._title(info)}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._host is not None
        assert self._info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._title(self._info), data={CONF_HOST: self._host}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._title(self._info),
                "model": self._info.type,
                "host": self._host,
            },
        )

    # ------------------------------------------------------------- reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._identify(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.serial)
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                HOST_SCHEMA, user_input or {CONF_HOST: entry.data[CONF_HOST]}
            ),
            errors=errors,
        )
