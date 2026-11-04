"""Konstanten für die Dachluke-Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dachluke"
PANEL_URL: Final = "dachluke"
STATIC_URL: Final = "/dachluke_files"
PANEL_ELEMENT: Final = "dachluke-panel"
STORAGE_VERSION: Final = 1
VERSION: Final = "1.14.0"

# Zeitraum der Dashboard-Diagramme: Schlüssel → (Stunden, Punkte pro Stunde)
CHART_RANGES: Final = {"6h": (6, 12), "24h": (24, 6), "3d": (72, 2), "7d": (168, 1)}

SIGNAL_UPDATE: Final = "dachluke_update_{}"

# ── Kern ────────────────────────────────────────────────────────────────
CONF_NAME: Final = "name"
CONF_COVER: Final = "cover"
CONF_POSITION_SENSOR: Final = "position_sensor"
CONF_HUMIDITY_SENSOR: Final = "humidity_sensor"
CONF_TEMP_SENSOR: Final = "temperature_sensor"
CONF_ROOM_HUMIDITY: Final = "room_humidity_sensor"
CONF_ROOM_TEMP: Final = "room_temperature_sensor"
CONF_WEATHER: Final = "weather"
CONF_LIGHTS: Final = "lights"
CONF_REQUIRE_LIGHT: Final = "require_light"
CONF_FAN: Final = "fan"
CONF_FAN_CONTROL: Final = "fan_control"

# ── Öffnen / Schließen ──────────────────────────────────────────────────
CONF_RISE_THRESHOLD: Final = "rise_threshold"
CONF_SHOWER_DETECT: Final = "shower_detect"
CONF_CLOSE_OFFSET: Final = "close_offset"
CONF_CLOSE_ABS: Final = "close_abs"
CONF_CLOSE_AH_OFFSET: Final = "close_ah_offset"
CONF_SHOWER_END_DROP: Final = "shower_end_drop"
CONF_HARD_CAP: Final = "hard_cap"
CONF_STALL_ENABLED: Final = "stall_enabled"
CONF_STALL_MINUTES: Final = "stall_minutes"
CONF_STALL_DELTA: Final = "stall_delta"
CONF_EXTEND: Final = "extend_while_drying"
CONF_COLD_ENABLED: Final = "cold_protect"
CONF_COLD_MIN: Final = "cold_min_temp"
CONF_MOLD_FACTOR: Final = "mold_factor"
CONF_VENT_PREDICTION: Final = "vent_prediction_sensor"
CONF_MIN_OPEN: Final = "min_open"
CONF_MAX_OPEN: Final = "max_open"
CONF_MANUAL_DURATION: Final = "manual_duration"
CONF_PAUSE_DURATION: Final = "pause_duration"
CONF_DEW_ENABLED: Final = "dew_enabled"
CONF_INDOOR_DEW: Final = "indoor_dew_sensor"
CONF_DEW_OFFSET: Final = "dew_offset"

# ── Positionen / Wetter ────────────────────────────────────────────────
CONF_POS_NORMAL: Final = "pos_normal"
CONF_POS_RESTRICTED: Final = "pos_restricted"
CONF_POS_TOLERANCE: Final = "pos_tolerance"
CONF_RESTRICTED: Final = "restricted_conditions"
CONF_BLOCKED: Final = "blocked_conditions"
CONF_BRIGHTSKY: Final = "brightsky"
CONF_RAIN_SENSOR: Final = "rain_sensor"
CONF_RAIN_THRESHOLD: Final = "rain_threshold"
BRIGHTSKY_URL: Final = "https://api.brightsky.dev/current_weather"

# ── Heizung / Frost / Nachlüften ───────────────────────────────────────
CONF_HEATING_ENABLED: Final = "heating_enabled"
CONF_CLIMATE: Final = "climate"
CONF_HEATING_VENT_TEMP: Final = "heating_vent_temp"
CONF_HEATING_RESTORE: Final = "heating_restore"
CONF_HEATING_NORMAL_TEMP: Final = "heating_normal_temp"
CONF_FROST_ENABLED: Final = "frost_enabled"
CONF_FROST_THRESHOLD: Final = "frost_threshold"
CONF_FROST_POSITION: Final = "frost_position"
CONF_FROST_DURATION: Final = "frost_duration"
CONF_SECOND_ENABLED: Final = "second_enabled"
CONF_SECOND_WAIT: Final = "second_wait"
CONF_SECOND_THRESHOLD: Final = "second_threshold"
CONF_SECOND_DURATION: Final = "second_duration"
CONF_SECOND_HEATING: Final = "second_heating"

# ── Tasten ─────────────────────────────────────────────────────────────
CONF_BUTTON_OPEN: Final = "button_open"
CONF_BUTTON_CLOSE: Final = "button_close"
CONF_REMOTE_OPEN: Final = "remote_open"
CONF_REMOTE_CLOSE: Final = "remote_close"

# ── Sicherheit ─────────────────────────────────────────────────────────
CONF_CONTACT: Final = "contact_sensor"
CONF_CONTACT_GRACE: Final = "contact_grace"
CONF_ALARM: Final = "alarm_entity"
CONF_ALARM_STATES: Final = "alarm_states"

# ── Benachrichtigungen ─────────────────────────────────────────────────
CONF_NOTIFY_APP: Final = "notify_app_service"
CONF_NOTIFY_PERSISTENT: Final = "notify_persistent"
CONF_ALEXA: Final = "alexa_entity"
CONF_ALEXA_MODE: Final = "alexa_mode"
CONF_ALEXA_VOLUME: Final = "alexa_volume"
CONF_DWD: Final = "dwd_sensor"

HEATING_RESTORE_PREVIOUS: Final = "previous"
HEATING_RESTORE_FIXED: Final = "fixed"

WEATHER_CONDITIONS: Final = [
    "rainy",
    "pouring",
    "snowy",
    "snowy-rainy",
    "lightning",
    "lightning-rainy",
    "hail",
    "windy",
    "windy-variant",
    "exceptional",
]
ALARM_STATE_OPTIONS: Final = [
    "armed_home",
    "armed_away",
    "armed_night",
    "armed_vacation",
    "armed_custom_bypass",
    "arming",
    "pending",
    "triggered",
]

DEFAULTS: Final[dict] = {
    CONF_LIGHTS: [],
    CONF_REQUIRE_LIGHT: False,
    CONF_FAN: None,
    CONF_FAN_CONTROL: True,
    CONF_TEMP_SENSOR: None,
    CONF_ROOM_HUMIDITY: None,
    CONF_ROOM_TEMP: None,
    CONF_WEATHER: None,
    CONF_RISE_THRESHOLD: 8.0,
    CONF_SHOWER_DETECT: 4.0,
    CONF_CLOSE_OFFSET: 3.0,
    CONF_CLOSE_ABS: 0.0,
    CONF_CLOSE_AH_OFFSET: 1.0,
    CONF_SHOWER_END_DROP: 3.0,
    CONF_HARD_CAP: 90,
    CONF_STALL_ENABLED: True,
    CONF_STALL_MINUTES: 10,
    CONF_STALL_DELTA: 1.0,
    CONF_EXTEND: True,
    CONF_COLD_ENABLED: True,
    CONF_COLD_MIN: 18.0,
    CONF_MOLD_FACTOR: 1.3,
    CONF_VENT_PREDICTION: None,
    CONF_MIN_OPEN: 5,
    CONF_MAX_OPEN: 20,
    CONF_MANUAL_DURATION: 15,
    CONF_PAUSE_DURATION: 10,
    CONF_DEW_ENABLED: False,
    CONF_INDOOR_DEW: None,
    CONF_DEW_OFFSET: 2.0,
    CONF_POS_NORMAL: 80,
    CONF_POS_RESTRICTED: 20,
    CONF_POS_TOLERANCE: 3,
    CONF_RESTRICTED: [
        "rainy",
        "pouring",
        "snowy",
        "snowy-rainy",
        "lightning",
        "lightning-rainy",
    ],
    CONF_BLOCKED: ["hail", "windy-variant"],
    CONF_BRIGHTSKY: False,
    CONF_RAIN_SENSOR: None,
    CONF_RAIN_THRESHOLD: 0.1,
    CONF_HEATING_ENABLED: False,
    CONF_CLIMATE: None,
    CONF_HEATING_VENT_TEMP: 15.0,
    CONF_HEATING_RESTORE: HEATING_RESTORE_PREVIOUS,
    CONF_HEATING_NORMAL_TEMP: 22.0,
    CONF_FROST_ENABLED: False,
    CONF_FROST_THRESHOLD: -5.0,
    CONF_FROST_POSITION: 10,
    CONF_FROST_DURATION: 8,
    CONF_SECOND_ENABLED: False,
    CONF_SECOND_WAIT: 25,
    CONF_SECOND_THRESHOLD: 60.0,
    CONF_SECOND_DURATION: 2,
    CONF_SECOND_HEATING: False,
    CONF_BUTTON_OPEN: None,
    CONF_BUTTON_CLOSE: None,
    CONF_REMOTE_OPEN: None,
    CONF_REMOTE_CLOSE: None,
    CONF_CONTACT: None,
    CONF_CONTACT_GRACE: 8,
    CONF_ALARM: None,
    CONF_ALARM_STATES: [
        "armed_away",
        "armed_night",
        "armed_vacation",
        "arming",
        "pending",
        "triggered",
    ],
    CONF_NOTIFY_APP: "",
    CONF_NOTIFY_PERSISTENT: True,
    CONF_ALEXA: None,
    CONF_ALEXA_MODE: "critical",
    CONF_ALEXA_VOLUME: "soft",
    CONF_DWD: None,
}

# Ereignistypen der Homematic(IP)-Local-Event-Entitäten
EVENT_SHORT: Final = {"press_short"}
EVENT_LONG: Final = {"press_long_release", "press_long_start"}

# Statuswerte (Enum-Sensor)
STATUS_READY: Final = "bereit"
STATUS_AUTO: Final = "lueftet_auto"
STATUS_MANUAL: Final = "lueftet_manuell"
STATUS_SECOND: Final = "nachlueften"
STATUS_PAUSED: Final = "pause"
STATUS_DISABLED: Final = "deaktiviert"
STATUS_ALARM: Final = "gesperrt_alarm"
STATUS_WEATHER: Final = "gesperrt_wetter"
STATUS_SENSOR: Final = "sensor_fehlt"
STATUS_OPTIONS: Final = [
    STATUS_READY,
    STATUS_AUTO,
    STATUS_MANUAL,
    STATUS_SECOND,
    STATUS_PAUSED,
    STATUS_DISABLED,
    STATUS_ALARM,
    STATUS_WEATHER,
    STATUS_SENSOR,
]

# Zähler der Analyse
COUNTERS: Final = [
    "open_auto",
    "open_manual",
    "close_humidity",
    "close_timer",
    "close_stall",
    "close_cold",
    "close_manual",
    "close_safety",
    "showers",
    "showers_missed",
    "sensor_failures",
]
