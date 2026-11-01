"""Einrichtung und Optionen über die Oberfläche."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    ALARM_STATE_OPTIONS,
    CONF_ALARM,
    CONF_ALARM_STATES,
    CONF_ALEXA,
    CONF_ALEXA_MODE,
    CONF_ALEXA_VOLUME,
    CONF_BLOCKED,
    CONF_BUTTON_CLOSE,
    CONF_BUTTON_OPEN,
    CONF_CLIMATE,
    CONF_CLOSE_ABS,
    CONF_CLOSE_AH_OFFSET,
    CONF_CLOSE_OFFSET,
    CONF_CONTACT,
    CONF_CONTACT_GRACE,
    CONF_COVER,
    CONF_DEW_ENABLED,
    CONF_DEW_OFFSET,
    CONF_DWD,
    CONF_FAN,
    CONF_FROST_DURATION,
    CONF_FROST_ENABLED,
    CONF_FROST_POSITION,
    CONF_FROST_THRESHOLD,
    CONF_HARD_CAP,
    CONF_HEATING_ENABLED,
    CONF_HEATING_NORMAL_TEMP,
    CONF_HEATING_RESTORE,
    CONF_HEATING_VENT_TEMP,
    CONF_HUMIDITY_SENSOR,
    CONF_INDOOR_DEW,
    CONF_LIGHTS,
    CONF_MANUAL_DURATION,
    CONF_MAX_OPEN,
    CONF_MIN_OPEN,
    CONF_NAME,
    CONF_NOTIFY_APP,
    CONF_NOTIFY_PERSISTENT,
    CONF_PAUSE_DURATION,
    CONF_POS_NORMAL,
    CONF_POS_RESTRICTED,
    CONF_POS_TOLERANCE,
    CONF_POSITION_SENSOR,
    CONF_REMOTE_CLOSE,
    CONF_REMOTE_OPEN,
    CONF_REQUIRE_LIGHT,
    CONF_RESTRICTED,
    CONF_RISE_THRESHOLD,
    CONF_SECOND_DURATION,
    CONF_SECOND_ENABLED,
    CONF_SECOND_HEATING,
    CONF_SECOND_THRESHOLD,
    CONF_SECOND_WAIT,
    CONF_SHOWER_DETECT,
    CONF_SHOWER_END_DROP,
    CONF_STALL_DELTA,
    CONF_STALL_ENABLED,
    CONF_STALL_MINUTES,
    CONF_TEMP_SENSOR,
    CONF_WEATHER,
    DEFAULTS,
    DOMAIN,
    HEATING_RESTORE_FIXED,
    HEATING_RESTORE_PREVIOUS,
    WEATHER_CONDITIONS,
)

# ── Bausteine ──────────────────────────────────────────────────────────


def _entity(domain: str | list[str], *, multiple: bool = False, device_class: str | None = None) -> sel.EntitySelector:
    cfg: dict[str, Any] = {"domain": domain, "multiple": multiple}
    if device_class:
        cfg["device_class"] = device_class
    return sel.EntitySelector(sel.EntitySelectorConfig(**cfg))


def _num(minimum: float, maximum: float, step: float, unit: str | None = None, box: bool = False) -> sel.NumberSelector:
    return sel.NumberSelector(
        sel.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=sel.NumberSelectorMode.BOX if box else sel.NumberSelectorMode.SLIDER,
        )
    )


def _select(options: list[str], key: str, *, multiple: bool = False) -> sel.SelectSelector:
    return sel.SelectSelector(
        sel.SelectSelectorConfig(
            options=options,
            multiple=multiple,
            translation_key=key,
            mode=sel.SelectSelectorMode.DROPDOWN if not multiple else sel.SelectSelectorMode.LIST,
        )
    )


BOOL = sel.BooleanSelector()

# Feld → (Selektor, optional?)  Optionale Felder lassen sich leeren.
FIELDS: dict[str, tuple[Any, bool]] = {
    CONF_COVER: (_entity("cover"), False),
    CONF_POSITION_SENSOR: (_entity("sensor"), False),
    CONF_HUMIDITY_SENSOR: (_entity("sensor", device_class="humidity"), False),
    CONF_TEMP_SENSOR: (_entity("sensor", device_class="temperature"), True),
    CONF_WEATHER: (_entity("weather"), True),
    CONF_LIGHTS: (_entity("light", multiple=True), True),
    CONF_REQUIRE_LIGHT: (BOOL, False),
    CONF_FAN: (_entity(["fan", "switch"]), True),
    CONF_RISE_THRESHOLD: (_num(2, 25, 1, "%/5 min"), False),
    CONF_SHOWER_DETECT: (_num(1, 15, 1, "%/5 min"), False),
    CONF_CLOSE_OFFSET: (_num(0, 15, 1, "%"), False),
    CONF_CLOSE_ABS: (_num(0, 90, 1, "%"), False),
    CONF_CLOSE_AH_OFFSET: (_num(0.2, 5, 0.1, "g/m³"), False),
    CONF_SHOWER_END_DROP: (_num(1, 10, 1, "%"), False),
    CONF_HARD_CAP: (_num(30, 180, 10, "min"), False),
    CONF_STALL_ENABLED: (BOOL, False),
    CONF_STALL_MINUTES: (_num(5, 25, 1, "min"), False),
    CONF_STALL_DELTA: (_num(0.5, 5, 0.5, "%"), False),
    CONF_MIN_OPEN: (_num(1, 30, 1, "min"), False),
    CONF_MAX_OPEN: (_num(5, 120, 5, "min"), False),
    CONF_MANUAL_DURATION: (_num(2, 120, 1, "min"), False),
    CONF_PAUSE_DURATION: (_num(1, 120, 1, "min"), False),
    CONF_DEW_ENABLED: (BOOL, False),
    CONF_INDOOR_DEW: (_entity("sensor", device_class="temperature"), True),
    CONF_DEW_OFFSET: (_num(0, 10, 0.5, "°C"), False),
    CONF_POS_NORMAL: (_num(10, 100, 5, "%"), False),
    CONF_POS_RESTRICTED: (_num(5, 50, 5, "%"), False),
    CONF_POS_TOLERANCE: (_num(1, 10, 1, "%"), False),
    CONF_RESTRICTED: (_select(WEATHER_CONDITIONS, "weather_condition", multiple=True), False),
    CONF_BLOCKED: (_select(WEATHER_CONDITIONS, "weather_condition", multiple=True), False),
    CONF_HEATING_ENABLED: (BOOL, False),
    CONF_CLIMATE: (_entity("climate"), True),
    CONF_HEATING_VENT_TEMP: (_num(5, 20, 0.5, "°C"), False),
    CONF_HEATING_RESTORE: (_select([HEATING_RESTORE_PREVIOUS, HEATING_RESTORE_FIXED], "heating_restore"), False),
    CONF_HEATING_NORMAL_TEMP: (_num(15, 30, 0.5, "°C"), False),
    CONF_FROST_ENABLED: (BOOL, False),
    CONF_FROST_THRESHOLD: (_num(-15, 5, 1, "°C"), False),
    CONF_FROST_POSITION: (_num(5, 30, 5, "%"), False),
    CONF_FROST_DURATION: (_num(2, 20, 1, "min"), False),
    CONF_SECOND_ENABLED: (BOOL, False),
    CONF_SECOND_WAIT: (_num(5, 60, 5, "min"), False),
    CONF_SECOND_THRESHOLD: (_num(40, 85, 1, "%"), False),
    CONF_SECOND_DURATION: (_num(1, 10, 1, "min"), False),
    CONF_SECOND_HEATING: (BOOL, False),
    CONF_BUTTON_OPEN: (_entity("event"), True),
    CONF_BUTTON_CLOSE: (_entity("event"), True),
    CONF_REMOTE_OPEN: (_entity("event"), True),
    CONF_REMOTE_CLOSE: (_entity("event"), True),
    CONF_CONTACT: (_entity("binary_sensor"), True),
    CONF_CONTACT_GRACE: (_num(1, 60, 1, "s"), False),
    CONF_ALARM: (_entity("alarm_control_panel"), True),
    CONF_ALARM_STATES: (_select(ALARM_STATE_OPTIONS, "alarm_state", multiple=True), False),
    CONF_NOTIFY_APP: (sel.TextSelector(), True),
    CONF_NOTIFY_PERSISTENT: (BOOL, False),
    CONF_ALEXA: (_entity("notify"), True),
    CONF_ALEXA_MODE: (_select(["critical", "all"], "alexa_mode"), False),
    CONF_ALEXA_VOLUME: (_select(["x-soft", "soft", "medium", "loud", "x-loud"], "alexa_volume"), False),
    CONF_DWD: (_entity("sensor"), True),
}

CORE = [CONF_COVER, CONF_POSITION_SENSOR, CONF_HUMIDITY_SENSOR, CONF_TEMP_SENSOR, CONF_WEATHER, CONF_LIGHTS, CONF_REQUIRE_LIGHT, CONF_FAN]

STEPS: dict[str, list[str]] = {
    "core": CORE,
    "venting": [
        CONF_RISE_THRESHOLD,
        CONF_SHOWER_DETECT,
        CONF_CLOSE_AH_OFFSET,
        CONF_CLOSE_OFFSET,
        CONF_CLOSE_ABS,
        CONF_SHOWER_END_DROP,
        CONF_MIN_OPEN,
        CONF_MAX_OPEN,
        CONF_HARD_CAP,
        CONF_STALL_ENABLED,
        CONF_STALL_MINUTES,
        CONF_STALL_DELTA,
        CONF_MANUAL_DURATION,
        CONF_PAUSE_DURATION,
        CONF_DEW_ENABLED,
        CONF_INDOOR_DEW,
        CONF_DEW_OFFSET,
    ],
    "weather": [CONF_POS_NORMAL, CONF_POS_RESTRICTED, CONF_POS_TOLERANCE, CONF_RESTRICTED, CONF_BLOCKED, CONF_DWD],
    "heating": [
        CONF_HEATING_ENABLED,
        CONF_CLIMATE,
        CONF_HEATING_VENT_TEMP,
        CONF_HEATING_RESTORE,
        CONF_HEATING_NORMAL_TEMP,
        CONF_FROST_ENABLED,
        CONF_FROST_THRESHOLD,
        CONF_FROST_POSITION,
        CONF_FROST_DURATION,
    ],
    "second": [CONF_SECOND_ENABLED, CONF_SECOND_WAIT, CONF_SECOND_THRESHOLD, CONF_SECOND_DURATION, CONF_SECOND_HEATING],
    "buttons": [CONF_BUTTON_OPEN, CONF_BUTTON_CLOSE, CONF_REMOTE_OPEN, CONF_REMOTE_CLOSE],
    "safety": [CONF_CONTACT, CONF_CONTACT_GRACE, CONF_ALARM, CONF_ALARM_STATES],
    "notify": [CONF_NOTIFY_APP, CONF_NOTIFY_PERSISTENT, CONF_ALEXA, CONF_ALEXA_MODE, CONF_ALEXA_VOLUME],
}


def _schema(keys: list[str], values: dict[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {}
    for key in keys:
        selector, optional = FIELDS[key]
        current = values.get(key, DEFAULTS.get(key))
        if optional:
            marker = vol.Optional(key, description={"suggested_value": current} if current not in (None, "", []) else None)
        else:
            marker = vol.Required(key, default=current) if current is not None else vol.Required(key)
        schema[marker] = selector
    return vol.Schema(schema)


def _clean(keys: list[str], user_input: dict[str, Any]) -> dict[str, Any]:
    """Nicht ausgefüllte optionale Felder bewusst leeren."""
    result = {}
    for key in keys:
        if key in user_input:
            result[key] = user_input[key]
        else:
            result[key] = [] if key == CONF_LIGHTS else ("" if key == CONF_NOTIFY_APP else None)
    return result


def _validate(values: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if values.get(CONF_HEATING_ENABLED) and not values.get(CONF_CLIMATE):
        errors[CONF_CLIMATE] = "climate_required"
    if values.get(CONF_DEW_ENABLED) and not values.get(CONF_INDOOR_DEW):
        errors[CONF_INDOOR_DEW] = "dew_sensor_required"
    if values.get(CONF_REQUIRE_LIGHT) and not values.get(CONF_LIGHTS):
        errors[CONF_LIGHTS] = "lights_required"
    app = (values.get(CONF_NOTIFY_APP) or "").strip()
    if app and not app.startswith("notify."):
        errors[CONF_NOTIFY_APP] = "notify_service"
    return errors


class DachlukeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Erste Einrichtung."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_COVER])
            self._abort_if_unique_id_configured()
            values = {**DEFAULTS, **_clean(CORE, user_input)}
            errors = _validate(values)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data={}, options=values)
        schema = vol.Schema({vol.Required(CONF_NAME, default="Dachluke"): sel.TextSelector()}).extend(
            _schema(CORE, user_input or {}).schema
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DachlukeOptionsFlow()


class DachlukeOptionsFlow(OptionsFlow):
    """Einstellungen ändern – gegliedert in Bereiche."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=list(STEPS))

    async def _form(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        current = {**DEFAULTS, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            values = {**current, **_clean(STEPS[step], user_input)}
            errors = _validate(values)
            if not errors:
                return self.async_create_entry(data=values)
            current = {**current, **user_input}
        return self.async_show_form(step_id=step, data_schema=_schema(STEPS[step], current), errors=errors)

    async def async_step_core(self, user_input=None) -> ConfigFlowResult:
        return await self._form("core", user_input)

    async def async_step_venting(self, user_input=None) -> ConfigFlowResult:
        return await self._form("venting", user_input)

    async def async_step_weather(self, user_input=None) -> ConfigFlowResult:
        return await self._form("weather", user_input)

    async def async_step_heating(self, user_input=None) -> ConfigFlowResult:
        return await self._form("heating", user_input)

    async def async_step_second(self, user_input=None) -> ConfigFlowResult:
        return await self._form("second", user_input)

    async def async_step_buttons(self, user_input=None) -> ConfigFlowResult:
        return await self._form("buttons", user_input)

    async def async_step_safety(self, user_input=None) -> ConfigFlowResult:
        return await self._form("safety", user_input)

    async def async_step_notify(self, user_input=None) -> ConfigFlowResult:
        return await self._form("notify", user_input)
