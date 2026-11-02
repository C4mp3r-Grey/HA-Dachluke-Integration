"""Sensoren: Status, Messwerte und Analyse-Zähler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COUNTERS, STATUS_OPTIONS
from .controller import DachlukeController
from .entity import DachlukeEntity


@dataclass(frozen=True, kw_only=True)
class DachlukeSensorDescription(SensorEntityDescription):
    value: Callable[[DachlukeController], Any]
    attrs: Callable[[DachlukeController], dict[str, Any]] | None = None


SENSORS: tuple[DachlukeSensorDescription, ...] = (
    DachlukeSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value=lambda c: c.status,
        attrs=lambda c: {
            "hindernisse_oeffnen": c.open_blockers(),
            "zielposition": c.target(),
            "uebliche_raumfeuchte": c.reference()[0],
            "uebliche_raumfeuchte_absolut": c.reference()[1],
            "aussenfeuchte_absolut": c.outdoor_abs_humidity(),
            "aussenwerte_quelle": c.outdoor_source(),
            "niederschlag": c.rain_value()[0],
            "schliessen_bei": c.close_targets()[0],
            "schliessen_bei_absolut": c.close_targets()[1],
            "pause_bis": c.pause_until.isoformat() if c.pause_until else None,
            "hoechstwert_feuchte": c.peak,
            "duschende": c.shower_end.isoformat() if c.shower_end else None,
            "ausgangsfeuchte_absolut": c.baseline_ah,
        },
    ),
    DachlukeSensorDescription(
        key="humidity_rise",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda c: c.rise,
    ),
    DachlukeSensorDescription(
        key="absolute_humidity",
        native_unit_of_measurement="g/m³",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda c: c.abs_humidity(),
    ),
    DachlukeSensorDescription(
        key="humidity_baseline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value=lambda c: c.baseline if c.mode != "idle" else None,
    ),
    DachlukeSensorDescription(
        key="vent_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda c: c.vent_end,
    ),
    DachlukeSensorDescription(
        key="last_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
        value=lambda c: c.last_duration,
    ),
    DachlukeSensorDescription(
        key="last_shower_duration",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        suggested_display_precision=0,
        value=lambda c: c.last_shower_minutes,
    ),
    DachlukeSensorDescription(
        key="last_event",
        value=lambda c: c.last_event,
        attrs=lambda c: {"protokoll": list(c.protocol)[-30:]},
    ),
    *(
        DachlukeSensorDescription(
            key=f"count_{name}",
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
            value=lambda c, n=name: c.counters[n],
            attrs=lambda c: {"seit": c.counters_since.isoformat()},
        )
        for name in COUNTERS
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    controller: DachlukeController = entry.runtime_data
    async_add_entities(DachlukeSensor(controller, d) for d in SENSORS)


class DachlukeSensor(DachlukeEntity, SensorEntity):
    entity_description: DachlukeSensorDescription
    _unrecorded_attributes = frozenset({"protokoll"})

    def __init__(self, controller: DachlukeController, description: DachlukeSensorDescription) -> None:
        super().__init__(controller, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.controller)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs:
            return self.entity_description.attrs(self.controller)
        return None

    @property
    def last_reset(self):
        if self.entity_description.key.startswith("count_"):
            return self.controller.counters_since
        return None
