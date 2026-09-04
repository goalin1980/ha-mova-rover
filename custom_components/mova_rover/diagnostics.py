"""Privacy-preserving Home Assistant diagnostics for MOVA Rover."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_MODEL, CONF_REGION, INTEGRATION_VERSION
from .redaction import fail_closed_diagnostics, safe_device, safe_property


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return bounded diagnostics with no account or device identifiers."""

    runtime_data = getattr(entry, "runtime_data", None)
    client = getattr(runtime_data, "client", None)
    coordinator = getattr(runtime_data, "coordinator", None)
    data = getattr(coordinator, "data", None)

    diagnostics: dict[str, Any] = {
        "integration": {
            "version": INTEGRATION_VERSION,
            "config_entry_version": entry.version,
            "region": entry.data.get(CONF_REGION),
            "configured_model": entry.data.get(CONF_MODEL),
        },
        "transport": {
            "type": "verified_https_rest_only",
            "authenticated": getattr(client, "authenticated", False),
            "last_http_status": getattr(client, "last_http_status", None),
            "last_cloud_code": getattr(client, "last_cloud_code", None),
            "mqtt_enabled": False,
            "commands_enabled": False,
        },
        "coordinator": {
            "available": coordinator is not None,
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "update_interval_seconds": int(
                getattr(
                    getattr(coordinator, "update_interval", None),
                    "total_seconds",
                    lambda: 0,
                )()
            ),
        },
    }

    if data is not None:
        diagnostics["device"] = safe_device(data.device)
        diagnostics["state"] = {
            "status": data.state.status,
            "raw_status": data.state.raw_status,
            "battery": data.state.battery,
            "online": data.state.online,
            "charging": data.state.charging,
            "cleaning": data.state.cleaning,
            "last_seen": data.state.last_seen.isoformat() if data.state.last_seen else None,
        }
        diagnostics["properties"] = [
            safe_property(item) for _, item in sorted(data.properties.items())
        ][:128]
    else:
        diagnostics["device"] = {"alias": "device_1"}
        diagnostics["state"] = None
        diagnostics["properties"] = []

    secrets = tuple(
        value
        for value in (
            entry.data.get(CONF_USERNAME),
            entry.data.get(CONF_PASSWORD),
            entry.data.get(CONF_DEVICE_ID),
        )
        if isinstance(value, str) and value
    )
    fallback = {
        "integration": {
            "version": INTEGRATION_VERSION,
            "config_entry_version": entry.version,
            "region": entry.data.get(CONF_REGION),
        },
        "transport": {
            "type": "verified_https_rest_only",
            "mqtt_enabled": False,
            "commands_enabled": False,
        },
        "redaction": {"status": "unsafe_fields_removed"},
    }
    audited = fail_closed_diagnostics(diagnostics, secrets, fallback)
    if audited is fallback or client is None:
        return audited
    try:
        serialized = json.dumps(audited, sort_keys=True, separators=(",", ":"), default=str)
        client.audit_serialized_session_secrets(serialized)
    except (TypeError, ValueError):
        return fallback
    return audited
