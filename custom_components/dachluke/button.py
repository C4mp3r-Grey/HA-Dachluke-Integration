"""Taste: Analyse-Zähler zurücksetzen."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import DachlukeController
from .entity import DachlukeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ResetButton(entry.runtime_data)])


class ResetButton(DachlukeEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "reset_counters")

    async def async_press(self) -> None:
        await self.controller.async_reset_counters()
