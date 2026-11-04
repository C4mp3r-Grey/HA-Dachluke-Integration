"""Diagnose-Download: Einstellungen, Zustand und vollständiges Protokoll."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_NOTIFY_APP, VERSION
from .controller import DachlukeController

# Der Name des Benachrichtigungsdienstes enthält oft den Gerätenamen
TO_REDACT = {CONF_NOTIFY_APP}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    controller: DachlukeController = entry.runtime_data
    sources = {}
    for key, eid in controller.snapshot().get("sources", {}).items():
        if not isinstance(eid, str):
            continue
        st = hass.states.get(eid)
        sources[key] = {
            "entity_id": eid,
            "state": st.state if st else None,
            "attributes": dict(st.attributes) if st else None,
            "last_changed": st.last_changed.isoformat() if st else None,
        }
    gust, gust_source = controller.wind_gust()
    rain, rain_source = controller.rain_value()
    return {
        "version": VERSION,
        "settings": async_redact_data({**controller.cfg}, TO_REDACT),
        "status": {
            "status": controller.status,
            "open_blockers": controller.open_blockers(),
            "target_position": controller.target(),
            "position_reason": controller.position_reason(),
            "outdoor_source": controller.outdoor_source(),
            "wind_gust_kmh": gust,
            "wind_source": gust_source,
            "storm_blocked": controller.storm_blocked(),
            "rain_mm": rain,
            "rain_source": rain_source,
            "brightsky": controller.bs,
            "close_targets": controller.close_targets(),
            "reference": controller.reference(),
            "wall_humidity": controller.wall_humidity(),
            "issues": controller.issues,
        },
        "sources": sources,
        # Enthält Zähler, gelernte Referenz und das vollständige Protokoll (bis 500 Einträge)
        "stored": async_redact_data(controller._serialize(), TO_REDACT),
    }
