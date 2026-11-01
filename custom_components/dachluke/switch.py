"""Schalter: Automatik und Pause."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import DachlukeController
from .entity import DachlukeEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    c: DachlukeController = entry.runtime_data
    async_add_entities([AutomaticSwitch(c), PauseSwitch(c)])


class AutomaticSwitch(DachlukeEntity, SwitchEntity):
    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "automatic")

    @property
    def is_on(self) -> bool:
        return self.controller.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_enabled(False)


class PauseSwitch(DachlukeEntity, SwitchEntity):
    def __init__(self, controller: DachlukeController) -> None:
        super().__init__(controller, "pause")

    @property
    def is_on(self) -> bool:
        return self.controller.paused()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_pause(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_pause(False)
