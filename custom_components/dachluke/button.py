"""Tasten: Jetzt lüften, Lüftung beenden, Analyse zurücksetzen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import DachlukeController
from .entity import DachlukeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    c: DachlukeController = entry.runtime_data
    async_add_entities([VentNowButton(c), StopVentingButton(c), ResetButton(c)])


class VentNowButton(DachlukeEntity, ButtonEntity):
    _attr_icon = "mdi:window-open-variant"

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "vent_now")

    async def async_press(self) -> None:
        await self.controller.async_vent_now()


class StopVentingButton(DachlukeEntity, ButtonEntity):
    _attr_icon = "mdi:window-closed-variant"

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "stop_venting")

    async def async_press(self) -> None:
        await self.controller.async_stop_venting()


class ResetButton(DachlukeEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "reset_counters")

    async def async_press(self) -> None:
        await self.controller.async_reset_counters()
