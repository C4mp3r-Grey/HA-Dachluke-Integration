"""Auswahl: Zeitraum der Dashboard-Diagramme."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CHART_RANGES
from .controller import OPERATING_MODES, DachlukeController
from .entity import DachlukeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ChartRangeSelect(entry.runtime_data), OperatingModeSelect(entry.runtime_data)])


class ChartRangeSelect(DachlukeEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:chart-timeline-variant"
    _attr_options = list(CHART_RANGES)

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "chart_range")

    @property
    def current_option(self) -> str:
        return self.controller.chart_range

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_chart_range(option)


class OperatingModeSelect(DachlukeEntity, SelectEntity):
    """Normal oder Wärme sparen (z. B. bei Heizungsausfall)."""

    _attr_icon = "mdi:radiator"
    _attr_options = OPERATING_MODES

    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "operating_mode")

    @property
    def current_option(self) -> str:
        return self.controller.operating_mode

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_operating_mode(option)
