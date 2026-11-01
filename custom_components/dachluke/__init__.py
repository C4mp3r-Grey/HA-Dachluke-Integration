"""Dachluke Badentlüftung – Steuerung, Analyse und Seitenleisten-Seite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN, PANEL_ELEMENT, PANEL_URL, STATIC_URL
from .controller import DachlukeController

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
VERSION = "1.2.0"

type DachlukeConfigEntry = ConfigEntry[DachlukeController]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_action)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DachlukeConfigEntry) -> bool:
    controller = DachlukeController(hass, entry)
    entry.runtime_data = controller
    await controller.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await _async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DachlukeConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_stop()
        remaining = [
            e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.entry_id != entry.entry_id
        ]
        if not remaining and hass.data.get(DOMAIN, {}).get("panel"):
            frontend.async_remove_panel(hass, PANEL_URL)
            hass.data[DOMAIN]["panel"] = False
    return ok


async def _async_reload(hass: HomeAssistant, entry: DachlukeConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get("static"):
        path = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(path), False)])
        data["static"] = True
    if not data.get("panel"):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name=PANEL_ELEMENT,
            sidebar_title="Dachluke",
            sidebar_icon="mdi:window-open-variant",
            module_url=f"{STATIC_URL}/dachluke-panel.js?v={VERSION}",
            require_admin=False,
            config={},
        )
        data["panel"] = True


def _entities(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    return {
        e.unique_id.removeprefix(prefix): e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.startswith(prefix)
    }


@websocket_api.websocket_command({vol.Required("type"): "dachluke/info"})
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Alles, was die Seitenleisten-Seite braucht."""
    result = []
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        controller: DachlukeController = entry.runtime_data
        result.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "entities": _entities(hass, entry),
                **controller.snapshot(),
            }
        )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "dachluke/action",
        vol.Required("entry_id"): str,
        vol.Required("action"): vol.In(["reset", "enable", "disable", "pause", "resume"]),
    }
)
@websocket_api.async_response
async def ws_action(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        connection.send_error(msg["id"], "not_found", "Eintrag nicht gefunden")
        return
    controller: DachlukeController = entry.runtime_data
    action = msg["action"]
    if action == "reset":
        await controller.async_reset_counters()
    elif action in ("enable", "disable"):
        await controller.async_set_enabled(action == "enable")
    else:
        await controller.async_set_pause(action == "pause")
    connection.send_result(msg["id"], {"ok": True})
