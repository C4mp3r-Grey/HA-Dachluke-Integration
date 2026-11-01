"""Binärsensor: Luke offen."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_POSITION_SENSOR
from .controller import DachlukeController
from .entity import DachlukeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DachlukeOpen(entry.runtime_data)])


class DachlukeOpen(DachlukeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "open")

    @property
    def is_on(self) -> bool | None:
        return self.controller.is_open()

    @callback
    def _position_changed(self, _event) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.controller.cfg[CONF_POSITION_SENSOR]], self._position_changed
            )
        )
