"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .controller import DachlukeController


class DachlukeEntity(Entity):
    """Basis: hängt am Controller und aktualisiert sich bei jeder Änderung."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: DachlukeController, key: str) -> None:
        self.controller = controller
        entry = controller.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Community (HACS)",
            model="Dachluke Badentlüftung",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_UPDATE.format(self.controller.entry.entry_id), self.async_write_ha_state
            )
        )
