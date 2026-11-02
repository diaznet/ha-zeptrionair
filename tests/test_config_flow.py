"""Config flow tests."""

from __future__ import annotations

import socket
from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zeptrionair_api.testing import FakeZeptrionDevice

from custom_components.zeptrionair.const import DOMAIN

from .conftest import SERIAL


def _closed_port() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"127.0.0.1:{sock.getsockname()[1]}"


def _zeroconf(host: str, name: str = f"zapp-{SERIAL}") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        port=int(host.rsplit(":", 1)[1]),
        hostname=f"{name}.local.",
        type="_zapp._tcp.local.",
        name=f"{name}._zapp._tcp.local.",
        properties={"type": "3340-2-B", "sw": "01.08.28"},
    )


async def test_user_flow(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: _closed_port()}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {fake.host} "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"zApp-{SERIAL}"
    assert result["data"] == {CONF_HOST: fake.host}
    assert result["result"].unique_id == SERIAL


async def test_user_flow_already_configured_updates_host(
    hass: HomeAssistant, fake: FakeZeptrionDevice
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "old-host"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: fake.host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == fake.host


async def test_zeroconf_flow(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    info = _zeroconf(fake.host)
    # The flow uses the discovered IP; point it at the fake's port.
    info = ZeroconfServiceInfo(
        ip_address=info.ip_address,
        ip_addresses=info.ip_addresses,
        port=info.port,
        hostname=info.hostname,
        type=info.type,
        name=info.name,
        properties=info.properties,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    # The flow connects to the bare IP (port 80), which the fake doesn't listen on.
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_zeroconf_confirm(
    hass: HomeAssistant, fake: FakeZeptrionDevice, monkeypatch: object
) -> None:
    import custom_components.zeptrionair.config_flow as flow_module

    # Route the discovered IP to the fake device's port.
    real_init = flow_module.ZeptrionDevice.__init__

    def patched_init(self: object, host: str, **kwargs: object) -> None:
        real_init(self, fake.host if host == "127.0.0.1" else host, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(flow_module.ZeptrionDevice, "__init__", patched_init)  # type: ignore[attr-defined]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(fake.host)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    assert result["description_placeholders"] == {
        "name": f"zApp-{SERIAL}",
        "model": "3340-2-B",
        "host": "127.0.0.1",
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "127.0.0.1"}

    # Same device announced again with a new address: host is updated, no new entry.
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    info = _zeroconf(fake.host)
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.7"),
        ip_addresses=[ip_address("192.0.2.7")],
        port=80,
        hostname=info.hostname,
        type=info.type,
        name=info.name,
        properties=info.properties,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.0.2.7"


async def test_zeroconf_serial_mismatch(
    hass: HomeAssistant, fake: FakeZeptrionDevice, monkeypatch: object
) -> None:
    import custom_components.zeptrionair.config_flow as flow_module

    real_init = flow_module.ZeptrionDevice.__init__

    def patched_init(self: object, host: str, **kwargs: object) -> None:
        real_init(self, fake.host, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(flow_module.ZeptrionDevice, "__init__", patched_init)  # type: ignore[attr-defined]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(fake.host, "zapp-11112222")
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_zeptrion"


async def test_zeroconf_not_zapp(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf(fake.host, "printer")
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_zeptrion"


async def test_dhcp_updates_known_device(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "old"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.0.2.9", hostname=f"zapp-{SERIAL}", macaddress="020000000001"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.0.2.9"


async def test_dhcp_registered_device_by_mac(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.0.2.10", hostname="espressif", macaddress="020000000001"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert loaded_entry.data[CONF_HOST] == "192.0.2.10"


async def test_dhcp_unknown_device(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.0.2.11", hostname="other", macaddress="aabbccddeeff"),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_zeptrion"


async def test_reconfigure(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data={CONF_HOST: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: _closed_port()}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: fake.host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == fake.host


async def test_reconfigure_wrong_device(hass: HomeAssistant, fake: FakeZeptrionDevice) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="11112222", data={CONF_HOST: "old"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: fake.host}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert entry.data[CONF_HOST] == "old"
