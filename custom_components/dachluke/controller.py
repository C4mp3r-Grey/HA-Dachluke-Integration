"""Steuerlogik und Analyse der Dachluke."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.components import persistent_notification
from homeassistant.const import UnitOfSpeed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import SpeedConverter

from . import logic
from .const import (
    CONF_ALARM,
    CONF_ALARM_STATES,
    CONF_ALEXA,
    CONF_ALEXA_MODE,
    CONF_ALEXA_VOLUME,
    CONF_BLOCKED,
    CONF_BRIGHTSKY,
    CONF_RAIN_SENSOR,
    CONF_RAIN_THRESHOLD,
    CONF_WIND_ENABLED,
    CONF_WIND_GUST,
    BRIGHTSKY_URL,
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
    CONF_FAN_CONTROL,
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
    CONF_EXTEND,
    CONF_COLD_ENABLED,
    CONF_COLD_MIN,
    CONF_MOLD_FACTOR,
    CONF_VENT_PREDICTION,
    CONF_STALL_ENABLED,
    CONF_STALL_MINUTES,
    CONF_TEMP_SENSOR,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_TEMP,
    CONF_WEATHER,
    COUNTERS,
    DEFAULTS,
    DOMAIN,
    EVENT_LONG,
    EVENT_SHORT,
    HEATING_RESTORE_PREVIOUS,
    SIGNAL_UPDATE,
    STATUS_ALARM,
    STATUS_AUTO,
    STATUS_DISABLED,
    STATUS_MANUAL,
    STATUS_PAUSED,
    STATUS_READY,
    STATUS_SECOND,
    STATUS_SENSOR,
    STATUS_WEATHER,
    STORAGE_VERSION,
    ISSUE_BRIGHTSKY,
    ISSUE_COVER_NOT_CLOSING,
    ISSUE_COVER_NOT_OPENING,
    ISSUE_HEATING_INEFFECTIVE,
    ISSUE_HUMIDITY_MISSING,
    ISSUE_POSITION_MISSING,
    ISSUES,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

MODE_IDLE = "idle"
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_SECOND = "second"

PENDING_SECONDS = 120
FAILURE_DELAY = timedelta(minutes=5)
SHOWER_CHECK = timedelta(minutes=10)
SHOWER_RESUME = timedelta(minutes=5)  # erneuter Anstieg bis 5 min nach Duschende = gleiche Dusche
PROTOCOL_LEN = 500
SETTLE_POLL = timedelta(seconds=5)
CONFIRM_DELAY = timedelta(seconds=30)
BUTTON_WINDOW = timedelta(seconds=90)
REF_INTERVAL = timedelta(minutes=15)
REF_QUIET = timedelta(hours=2)
REF_KEEP = timedelta(days=3)
REF_MIN_SAMPLES = 8
BS_INTERVAL = timedelta(minutes=10)
BS_MAX_AGE = timedelta(minutes=90)
CHECK_INTERVAL = timedelta(minutes=2)
SETTLED_FOR = timedelta(seconds=90)
VERIFY_CLOSE = timedelta(seconds=90)
VERIFY_CLOSE_2 = timedelta(seconds=150)
RAIN_HOLD = timedelta(minutes=15)
WIND_HOLD = timedelta(minutes=30)
BS_ISSUE_AFTER = timedelta(hours=1)
HEAT_CHECK = timedelta(minutes=3)
BAD_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN, "none", "", None)


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


class DachlukeController:
    """Hält den Zustand, reagiert auf Ereignisse und führt die Analyse."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}

        # Dauerhafter Zustand
        self.enabled = True
        self.mode = MODE_IDLE
        self.opened_at: datetime | None = None
        self.cap_base: datetime | None = None  # Beginn für die harte Obergrenze (neue Dusche setzt neu)
        self.vent_end: datetime | None = None
        self.baseline: float | None = None
        self.baseline_ah: float | None = None
        self.peak: float | None = None
        self.shower_end: datetime | None = None
        self.shower_start: datetime | None = None
        self.peak_time: datetime | None = None
        self.last_shower_minutes: float | None = None
        self.max_pos: float = 0.0
        self.pause_until: datetime | None = None
        self.second_at: datetime | None = None
        self.saved_setpoint: float | None = None
        self.heating_lowered = False
        self.fan_started = False
        self.chart_range = "24h"
        self.blocked_override = False
        self.last_duration: float | None = None
        self.last_open: datetime | None = None
        self.counters: dict[str, int] = {k: 0 for k in COUNTERS}
        self.counters_since: datetime = dt_util.utcnow()
        self.protocol: deque[dict[str, str]] = deque(maxlen=PROTOCOL_LEN)

        # Flüchtiger Zustand
        self.samples: deque[logic.Sample] = deque()
        self.ah_samples: deque[logic.Sample] = deque()
        self._room_samples: deque[logic.Sample] = deque()
        self.shower_ah_samples: deque[logic.Sample] = deque()
        self.shower_baseline_ah: float | None = None
        self.shower_baseline: float | None = None
        self.room_peak: float | None = None
        self.rise: float | None = None
        self.shower: dict[str, Any] | None = None
        self._pending: tuple[str, datetime] | None = None
        self._button_seen: dict[str, str] = {}
        self._button_at: dict[str, tuple[datetime, bool | str]] = {}
        self._settled_pos: float | None = None
        self._move_start: datetime | None = None
        self._last_pos_change: datetime | None = None
        self._stored_cfg: dict[str, Any] = {}
        self.ref_samples: deque[tuple] = deque()
        self.last_activity: datetime | None = None
        self.bs: dict[str, Any] = {}
        self.bs_fetched: datetime | None = None
        self._bs_failed = False
        self._bs_station: str | None = None
        self._last_restricted: bool | None = None
        self._last_rain_at: datetime | None = None
        self._reached_closed = True
        self._heating_warned = False
        self.heating_ineffective = False
        self._wall_at_open: float | None = None
        self._prediction_at_open: float | None = None
        self._extra_open = ""
        self._own_contexts: deque[str] = deque(maxlen=50)
        self._context_names: dict[str, str] = {}
        self._last_storm_at: datetime | None = None
        self._storm_logged = False
        self._bs_failed_since: datetime | None = None
        self.issues: dict[str, dict[str, str]] = {}

    # ════════════════════════════════════════════════════════════════════
    # Lebenszyklus
    # ════════════════════════════════════════════════════════════════════

    async def async_start(self) -> None:
        await self._restore()
        watched = [
            e
            for e in (
                self.cfg[CONF_HUMIDITY_SENSOR],
                self.cfg.get(CONF_TEMP_SENSOR),
                self.cfg.get(CONF_ROOM_HUMIDITY),
                self.cfg.get(CONF_ROOM_TEMP),
                self.cfg.get(CONF_CLIMATE) if self.cfg.get(CONF_ROOM_HUMIDITY) else None,
                self.pos_entity,
                self.cfg.get(CONF_WEATHER),
                self.cfg.get(CONF_RAIN_SENSOR),
                self.cfg.get(CONF_ALARM),
                self.cfg.get(CONF_CONTACT),
                self.cfg.get(CONF_INDOOR_DEW),
                *self._buttons().keys(),
                *(self.cfg.get(CONF_LIGHTS) or []),
            )
            if e
        ]
        for eid in self._buttons():
            st = self.hass.states.get(eid)
            if st:
                self._button_seen[eid] = st.state
        self._unsubs.append(async_track_state_change_event(self.hass, watched, self._handle_event))
        # Wer hat die Luke in HA bewegt? Dienstaufrufe und Automationen mitlesen
        self._unsubs.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._on_service_call))
        self._unsubs.append(self.hass.bus.async_listen("automation_triggered", self._on_run_started))
        self._unsubs.append(self.hass.bus.async_listen("script_started", self._on_run_started))
        self._unsubs.append(async_track_time_interval(self.hass, self._sample_reference, REF_INTERVAL))
        self._unsubs.append(async_track_time_interval(self.hass, self._consistency_tick, CHECK_INTERVAL))
        if self.cfg[CONF_BRIGHTSKY]:
            self._unsubs.append(async_track_time_interval(self.hass, self._bs_tick, BS_INTERVAL))
            self.hass.async_create_task(self._fetch_brightsky())
        hum = self._num(self.cfg[CONF_HUMIDITY_SENSOR])
        if hum is not None:
            self.samples.append((dt_util.utcnow(), hum))
        self._record_room(dt_util.utcnow())
        self.hass.async_create_task(self._resume_after_start())

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for key in list(self._timers):
            self._cancel(key)
        for key in ISSUES:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(key))
        self.issues.clear()
        await self._store.async_save(self._serialize())

    async def _restore(self) -> None:
        data = await self._store.async_load() or {}
        self.enabled = data.get("enabled", True)
        self.mode = data.get("mode", MODE_IDLE)
        self.opened_at = _dt(data.get("opened_at"))
        self.cap_base = _dt(data.get("cap_base"))
        self.vent_end = _dt(data.get("vent_end"))
        self.baseline = data.get("baseline")
        self.baseline_ah = data.get("baseline_ah")
        self.shower_baseline = data.get("shower_baseline")
        self.shower_baseline_ah = data.get("shower_baseline_ah")
        self.room_peak = data.get("room_peak")
        self.peak = data.get("peak")
        self.shower_end = _dt(data.get("shower_end"))
        self.shower_start = _dt(data.get("shower_start"))
        self.peak_time = _dt(data.get("peak_time"))
        self.last_shower_minutes = data.get("last_shower_minutes")
        self.max_pos = data.get("max_pos", 0.0)
        self._stored_cfg = data.get("cfg", {})
        self.last_activity = _dt(data.get("last_activity"))
        for item in data.get("ref", []):
            if (t := _dt(item[0])) is not None:
                rest = list(item[1:]) + [None] * (4 - len(item[1:]))
                self.ref_samples.append((t, *rest[:4]))
        self.pause_until = _dt(data.get("pause_until"))
        self.second_at = _dt(data.get("second_at"))
        self.saved_setpoint = data.get("saved_setpoint")
        self.heating_lowered = data.get("heating_lowered", False)
        self.fan_started = data.get("fan_started", False)
        self.chart_range = data.get("chart_range", "24h")
        self.blocked_override = data.get("blocked_override", False)
        self.last_duration = data.get("last_duration")
        self.last_open = _dt(data.get("last_open"))
        self.counters.update({k: v for k, v in data.get("counters", {}).items() if k in self.counters})
        self.counters_since = _dt(data.get("counters_since")) or dt_util.utcnow()
        self.protocol.extend(data.get("protocol", [])[-PROTOCOL_LEN:])

    def _serialize(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "opened_at": _ts(self.opened_at),
            "cap_base": _ts(self.cap_base),
            "vent_end": _ts(self.vent_end),
            "baseline": self.baseline,
            "baseline_ah": self.baseline_ah,
            "shower_baseline": self.shower_baseline,
            "room_peak": self.room_peak,
            "peak": self.peak,
            "shower_end": _ts(self.shower_end),
            "shower_start": _ts(self.shower_start),
            "peak_time": _ts(self.peak_time),
            "last_shower_minutes": self.last_shower_minutes,
            "max_pos": self.max_pos,
            "cfg": {k: v for k, v in self.cfg.items() if k in DEFAULTS},
            "last_activity": _ts(self.last_activity),
            "ref": [[_ts(r[0]), *r[1:]] for r in self.ref_samples],
            "shower_baseline_ah": self.shower_baseline_ah,
            "pause_until": _ts(self.pause_until),
            "second_at": _ts(self.second_at),
            "saved_setpoint": self.saved_setpoint,
            "heating_lowered": self.heating_lowered,
            "fan_started": self.fan_started,
            "chart_range": self.chart_range,
            "blocked_override": self.blocked_override,
            "last_duration": self.last_duration,
            "last_shower_minutes": self.last_shower_minutes,
            "last_open": _ts(self.last_open),
            "counters": self.counters,
            "counters_since": _ts(self.counters_since),
            "protocol": list(self.protocol),
        }

    async def _resume_after_start(self) -> None:
        """Nach (Neu-)Start Timer wiederherstellen und Widersprüche auflösen."""
        now = dt_util.utcnow()
        self._settled_pos = self.position()
        current = {k: v for k, v in self.cfg.items() if k in DEFAULTS}
        changed = [
            f"{k}: {self._stored_cfg.get(k)!s} → {v!s}"
            for k, v in current.items()
            if self._stored_cfg and self._stored_cfg.get(k) != v
        ]
        self._log(
            "START",
            f"Version {VERSION}; Anstieg ab {self.cfg[CONF_RISE_THRESHOLD]} %/5 min, Nachlüften {self.cfg[CONF_MAX_OPEN]} min, "
            f"Licht nötig: {'ja' if self.cfg[CONF_REQUIRE_LIGHT] else 'nein'}, "
            f"Raumsensor: {'ja' if self.cfg.get(CONF_ROOM_HUMIDITY) else 'nein'}, "
            f"absolute Feuchte: {self._abs_source_text()}, "
            f"Stagnation: {'ja' if self.cfg[CONF_STALL_ENABLED] else 'nein'}, "
            f"Außenwerte: {'DWD (Bright Sky)' if self.cfg[CONF_BRIGHTSKY] else 'Wetter-Entität'}, "
            f"Regen: {'Sensor' if self.cfg.get(CONF_RAIN_SENSOR) else 'DWD-Station' if self.cfg[CONF_BRIGHTSKY] else 'Wetterzustand'}",
        )
        if changed:
            self._log("EINSTELLUNGEN", "Geändert: " + "; ".join(changed)[:900])
        if self.pause_until:
            if self.pause_until <= now:
                self.pause_until = None
            else:
                self._at("pause", self.pause_until, self._pause_elapsed)
        if self.second_at:
            if self.second_at <= now:
                self.second_at = None
            else:
                self._at("second_wait", self.second_at, self._second_wait_elapsed)

        open_ = self.is_open()
        if self.mode != MODE_IDLE:
            if open_ is False:
                await self._finish_vent("neustart")
                self._log("NEUSTART", "Luke war beim Neustart schon zu – Lüftung beendet")
            elif self.vent_end and self.vent_end <= now:
                await self._close("timer", "Lüftungszeit während Neustart abgelaufen")
            elif self.vent_end:
                self._at("vent", self.vent_end, self._vent_elapsed)
                if self.mode == MODE_AUTO and self.shower_end:
                    self._schedule_stall_check(max(self.shower_end, now))
        elif open_:
            # Offen, aber keine bekannte Lüftung: wie manuelles Öffnen behandeln
            self.mode = MODE_MANUAL
            self.opened_at = now
            self.vent_end = now + timedelta(minutes=self._manual_minutes())
            self._at("vent", self.vent_end, self._vent_elapsed)
            self._log("NEUSTART", "Luke beim Start offen vorgefunden – Timer gestartet")
        elif self.heating_lowered or self.fan_started:
            await self._heating_restore()
            await self._fan_off()
        self._publish()

    # ════════════════════════════════════════════════════════════════════
    # Lesen von Zuständen
    # ════════════════════════════════════════════════════════════════════

    def _state(self, eid: str | None) -> State | None:
        return self.hass.states.get(eid) if eid else None

    def _num(self, eid: str | None) -> float | None:
        st = self._state(eid)
        if st is None or st.state in BAD_STATES:
            return None
        try:
            return float(st.state)
        except ValueError:
            return None

    @property
    def pos_entity(self) -> str:
        """Quelle der Position: eigener Sensor (z. B. HmIP-BROLL Kanal 3), sonst das Cover selbst."""
        return self.cfg.get(CONF_POSITION_SENSOR) or self.cfg[CONF_COVER]

    @property
    def has_position_sensor(self) -> bool:
        return bool(self.cfg.get(CONF_POSITION_SENSOR))

    @staticmethod
    def _pos_from_state(state: State | None) -> float | None:
        """Position in % aus einem Sensor oder einem Cover (current_position, sonst offen/zu)."""
        if state is None or state.state in BAD_STATES:
            return None
        if state.domain == "cover":
            cp = state.attributes.get("current_position")
            if cp is not None:
                try:
                    return float(cp)
                except (TypeError, ValueError):
                    return None
            if state.state == "closed":
                return 0.0
            if state.state in ("open", "opening", "closing"):
                return 100.0  # Cover ohne Positionsangabe: nur offen/zu bekannt
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def position(self) -> float | None:
        pos = self._pos_from_state(self._state(self.pos_entity))
        if pos is None and self.has_position_sensor:
            # Ersatzwert vom Cover, nur für Anzeige und Entscheidungen, nicht fürs Sicherheitsnetz
            return self._pos_from_state(self._state(self.cfg[CONF_COVER]))
        return pos

    def reliable_open(self) -> bool | None:
        """Nur aus der Positionsquelle (ohne Ersatzwert) – für das Sicherheitsnetz."""
        pos = self._pos_from_state(self._state(self.pos_entity))
        return None if pos is None else pos > 0

    def is_open(self) -> bool | None:
        pos = self.position()
        return None if pos is None else pos > 0

    def humidity(self) -> float | None:
        return self._num(self.cfg[CONF_HUMIDITY_SENSOR])

    def temperature(self) -> float | None:
        return self._num(self.cfg.get(CONF_TEMP_SENSOR))

    # Zwei Rollen: Der Sensor an der Dusche erkennt Beginn und Ende des Duschens,
    # der (optionale) Raumsensor entscheidet über das Schließen.

    @property
    def has_room(self) -> bool:
        return bool(self.cfg.get(CONF_ROOM_HUMIDITY))

    def room_humidity(self) -> float | None:
        if not self.has_room:
            return self.humidity()
        eid = self.cfg[CONF_ROOM_HUMIDITY]
        if eid.startswith("climate."):
            # Manche Thermostate liefern die Feuchte nur als Attribut
            st = self._state(eid)
            try:
                return float(st.attributes.get("current_humidity")) if st else None
            except (TypeError, ValueError):
                return None
        return self._num(eid)

    def _abs_source_text(self) -> str:
        """Für die Startmeldung: Ist eine Temperaturquelle eingerichtet, und liefert sie schon?"""
        configured = (
            bool(self.cfg.get(CONF_ROOM_TEMP) or self.cfg.get(CONF_CLIMATE))
            if self.has_room
            else bool(self.cfg.get(CONF_TEMP_SENSOR))
        )
        if not configured:
            return "nein (keine Temperatur eingerichtet)"
        return "ja" if self.room_temperature() is not None else "ja, Temperatur aber noch nicht verfügbar"

    def room_temperature(self) -> float | None:
        if not self.has_room:
            return self.temperature()
        if self.cfg.get(CONF_ROOM_TEMP):
            return self._num(self.cfg[CONF_ROOM_TEMP])
        clim = self._state(self.cfg.get(CONF_CLIMATE))
        if clim is not None:
            try:
                return float(clim.attributes.get("current_temperature"))
            except (TypeError, ValueError):
                return None
        return None

    @property
    def room_samples(self) -> deque[logic.Sample]:
        return self._room_samples if self.has_room else self.samples

    def abs_humidity(self) -> float | None:
        """Absolute Feuchte der Raumluft (Raumsensor, sonst Duschsensor)."""
        hum, temp = self.room_humidity(), self.room_temperature()
        if hum is None or temp is None:
            return None
        return logic.absolute_humidity(temp, hum)

    def shower_abs_humidity(self) -> float | None:
        hum, temp = self.humidity(), self.temperature()
        if hum is None or temp is None:
            return None
        return logic.absolute_humidity(temp, hum)

    def _trim(self, samples: deque, now: datetime) -> None:
        while samples and samples[0][0] < now - timedelta(minutes=30):
            samples.popleft()

    def _record_room(self, now: datetime) -> None:
        if self.has_room:
            hum = self.room_humidity()
            if hum is not None and (not self._room_samples or self._room_samples[-1][1] != hum):
                self._room_samples.append((now, hum))
                self._trim(self._room_samples, now)
        hum = self.room_humidity()
        if hum is not None and self.mode != MODE_IDLE:
            self.room_peak = hum if self.room_peak is None else max(self.room_peak, hum)
        ah = self.abs_humidity()
        if ah is not None and (not self.ah_samples or self.ah_samples[-1][1] != ah):
            self.ah_samples.append((now, ah))
            self._trim(self.ah_samples, now)
        sah = self.shower_abs_humidity()
        if self.has_room and sah is not None and (not self.shower_ah_samples or self.shower_ah_samples[-1][1] != sah):
            self.shower_ah_samples.append((now, sah))
            self._trim(self.shower_ah_samples, now)

    def _record_ah(self, now: datetime) -> None:
        self._record_room(now)

    def _set_baselines(self, now: datetime) -> None:
        self.shower_baseline = logic.baseline_humidity(self.samples, now)
        self.shower_baseline_ah = (
            logic.baseline_humidity(self.shower_ah_samples, now) if self.shower_ah_samples else None
        )
        self.baseline = logic.baseline_humidity(self.room_samples, now)
        self.baseline_ah = logic.baseline_humidity(self.ah_samples, now) if self.ah_samples else None
        self.room_peak = self.room_humidity()

    def _fmt(self, value: float | None, unit: str, digits: int = 0) -> str:
        return "?" if value is None else f"{value:.{digits}f}{unit}"

    def context(self) -> str:
        """Umgebung für das Protokoll: innen, außen, Licht, Lüfter, Heizung."""
        shower = f"Dusche {self._fmt(self.humidity(), ' %')}"
        if self.cfg.get(CONF_TEMP_SENSOR):
            shower += f" {self._fmt(self.temperature(), ' °C', 1)} {self._fmt(self.shower_abs_humidity(), ' g/m³', 1)}"
        parts = [shower]
        if self.has_room:
            parts.append(
                f"Raum {self._fmt(self.room_humidity(), ' %')} {self._fmt(self.room_temperature(), ' °C', 1)} "
                f"{self._fmt(self.abs_humidity(), ' g/m³', 1)}"
            )
        if self.cfg.get(CONF_WEATHER):
            parts.append(
                f"außen {self.weather_state() or '?'} {self._fmt(self._weather_attr('temperature'), ' °C', 1)} "
                f"{self._fmt(self._weather_attr('humidity'), ' %')} TP {self._fmt(self._weather_attr('dew_point'), ' °C', 1)} "
                f"[{self.outdoor_source()}]"
            )
        if self.cfg.get(CONF_LIGHTS):
            parts.append(f"Licht {'an' if self.lights_on() else 'aus'}")
        if fan := self._state(self.cfg.get(CONF_FAN)):
            parts.append(f"Lüfter {fan.state}")
        if clim := self._state(self.cfg.get(CONF_CLIMATE)):
            parts.append(f"Heizung {clim.state} {clim.attributes.get('temperature', '?')} °C")
        return ", ".join(parts)

    # ── Referenz: übliche Raumfeuchte in Ruhephasen ───────────────────────
    def outdoor_abs_humidity(self) -> float | None:
        temp, hum = self._weather_attr("temperature"), self._weather_attr("humidity")
        if temp is None or hum is None:
            return None
        return logic.absolute_humidity(temp, hum)

    def reference(self) -> tuple[float | None, float | None]:
        if len(self.ref_samples) < REF_MIN_SAMPLES:
            return None, None
        return (
            logic.median([r[1] for r in self.ref_samples]),
            logic.median([r[2] for r in self.ref_samples]),
        )

    def shower_reference(self) -> tuple[float | None, float | None]:
        vals = [r for r in self.ref_samples if len(r) > 3 and r[3] is not None]
        if len(vals) < REF_MIN_SAMPLES:
            return None, None
        return logic.median([r[3] for r in vals]), logic.median([r[4] for r in vals])

    def shower_targets(self) -> tuple[float | None, float | None]:
        ref_rh, ref_ah = self.shower_reference()
        return logic.close_targets(
            baseline=self.shower_baseline,
            baseline_ah=self.shower_baseline_ah,
            ref_rh=ref_rh,
            ref_ah=ref_ah,
            outdoor_ah=self.outdoor_abs_humidity(),
        )

    def shower_dry(self) -> tuple[bool, str]:
        """Hat sich die feuchte Luft über der Dusche verzogen? (nur mit Raumsensor relevant)"""
        if not self.has_room:
            return True, ""
        t_rh, t_ah = self.shower_targets()
        sah = self.shower_abs_humidity()
        if sah is not None and t_ah is not None:
            limit = t_ah + float(self.cfg[CONF_CLOSE_AH_OFFSET])
            return sah <= limit, f"Dusche {sah:.1f} g/m³ (Grenze {limit:.1f})"
        hum = self.humidity()
        if hum is not None and t_rh is not None:
            limit = t_rh + float(self.cfg[CONF_CLOSE_OFFSET])
            return hum <= limit, f"Dusche {hum:.0f} % (Grenze {limit:.0f} %)"
        return True, ""

    def close_targets(self) -> tuple[float | None, float | None]:
        ref_rh, ref_ah = self.reference()
        return logic.close_targets(
            baseline=self.baseline,
            baseline_ah=self.baseline_ah,
            ref_rh=ref_rh,
            ref_ah=ref_ah,
            outdoor_ah=self.outdoor_abs_humidity(),
        )

    def target_source(self, *, absolute: bool) -> str:
        ref_rh, ref_ah = self.reference()
        base, ref = (self.baseline_ah, ref_ah) if absolute else (self.baseline, ref_rh)
        out = self.outdoor_abs_humidity()
        _, target_ah = self.close_targets()
        if absolute and out is not None and target_ah is not None and abs(target_ah - (out + 0.5)) < 0.01:
            return f"Außenluft {out:.1f} g/m³ + 0,5"
        if ref is not None and (base is None or ref < base):
            return f"übliche Raumfeuchte statt erhöhter Ausgangsfeuchte {self._fmt(base, '', 1 if absolute else 0)}"
        return "Ausgangsfeuchte vor dem Duschen"

    def _target_text(self) -> str:
        ref_rh, ref_ah = self.reference()
        t_rh, t_ah = self.close_targets()
        out = self.outdoor_abs_humidity()
        txt = f"Schließen bei {self._fmt(t_rh, ' %')}"
        if t_ah is not None:
            txt += f" bzw. {self._fmt(t_ah, ' g/m³', 1)}"
        txt += f" + Offset; üblich {self._fmt(ref_rh, ' %')}" + (f"/{self._fmt(ref_ah, ' g/m³', 1)}" if ref_ah is not None else "")
        if ref_rh is None:
            txt += f" (Referenz lernt noch, {len(self.ref_samples)}/{REF_MIN_SAMPLES} Werte)"
        if out is not None:
            txt += f"; außen {out:.1f} g/m³"
        return txt

    @callback
    def _sample_reference(self, now: datetime) -> None:
        """Alle 15 min in Ruhephasen die Raumfeuchte merken (für die Referenz)."""
        now = dt_util.utcnow()
        if self.mode != MODE_IDLE or self.is_open():
            return
        if self.last_activity and now - self.last_activity < REF_QUIET:
            return
        rh, ah = self.room_humidity(), self.abs_humidity()
        if rh is None:
            return
        if self.has_room:
            self.ref_samples.append((now, rh, ah, self.humidity(), self.shower_abs_humidity()))
        else:
            self.ref_samples.append((now, rh, ah, None, None))
        while self.ref_samples and self.ref_samples[0][0] < now - REF_KEEP:
            self.ref_samples.popleft()
        self._store.async_delay_save(self._serialize, 30)

    def wall_humidity(self) -> tuple[float | None, float | None]:
        """Feuchte an der kältesten Wandstelle (Schimmelrisiko) und deren Temperatur."""
        t_in, rh_in, t_out = self.room_temperature(), self.room_humidity(), self._weather_attr("temperature")
        if None in (t_in, rh_in, t_out):
            return None, None
        return logic.wall_humidity(t_in, rh_in, t_out, float(self.cfg[CONF_MOLD_FACTOR]))

    def vent_prediction(self) -> float | None:
        return self._num(self.cfg.get(CONF_VENT_PREDICTION))

    def position_reason(self) -> str:
        """Warum die Zielposition so gewählt wird."""
        weather = self.weather_state()
        outdoor = self._weather_attr("temperature")
        if weather in (self.cfg[CONF_BLOCKED] or []):
            return f"Wetter gesperrt ({weather})"
        if self.frost_active():
            return f"Frost: außen {self._fmt(outdoor, ' °C', 1)} unter {float(self.cfg[CONF_FROST_THRESHOLD]):.0f} °C"
        rain, rain_src = self.rain_value()
        if rain is not None:
            if rain >= float(self.cfg[CONF_RAIN_THRESHOLD]):
                return f"Regen {rain:.1f} mm ({rain_src})"
            return f"kein Regen ({rain_src} {rain:.1f} mm)"
        if weather in (self.cfg[CONF_RESTRICTED] or []):
            return f"eingeschränktes Wetter ({weather})"
        if not self.cfg.get(CONF_WEATHER):
            return "kein Wetter eingetragen – normale Öffnung"
        return f"normales Wetter ({weather or '?'})"

    @callback
    def _on_run_started(self, event: Event) -> None:
        kind = "Automation" if event.event_type == "automation_triggered" else "Skript"
        name = event.data.get("name") or event.data.get("entity_id") or "?"
        self._context_names[event.context.id] = f"{kind} „{name}“"
        if len(self._context_names) > 100:
            self._context_names.pop(next(iter(self._context_names)))

    @callback
    def _on_service_call(self, event: Event) -> None:
        data = event.data
        if data.get("domain") != "cover":
            return
        target = (data.get("service_data") or {}).get("entity_id")
        targets = [target] if isinstance(target, str) else list(target or [])
        if self.cfg[CONF_COVER] not in targets:
            return
        ctx = event.context
        if ctx.id in self._own_contexts:
            return
        service = data.get("service")
        position = (data.get("service_data") or {}).get("position")
        role = "close" if service == "close_cover" or (service == "set_cover_position" and position == 0) else "open"
        if service == "stop_cover":
            return
        self.hass.async_create_task(self._remember_service_source(role, ctx))

    async def _remember_service_source(self, role: str, ctx: Context) -> None:
        name = self._context_names.get(ctx.id) or (self._context_names.get(ctx.parent_id) if ctx.parent_id else None)
        if not name and ctx.user_id:
            user = await self.hass.auth.async_get_user(ctx.user_id)
            name = f"Benutzer {user.name}" if user and user.name else "angemeldeter Benutzer"
        if not name:
            name = "Home Assistant (ohne Benutzer)"
        self._button_at[role] = (dt_util.utcnow(), f"über HA: {name}")

    def _manual_source(self, role: str) -> str:
        hit = self._button_at.get(role)
        if hit and dt_util.utcnow() - hit[0] <= BUTTON_WINDOW:
            if isinstance(hit[1], str):
                return hit[1]
            return "per Fernbedienung" if hit[1] else "per Taste am Gerät"
        return "außerhalb von HA (Taste am Gerät, CCU-Programm oder Direktverknüpfung)"

    def lights_on(self) -> bool:
        return any(
            (st := self._state(e)) is not None and st.state == STATE_ON
            for e in self.cfg.get(CONF_LIGHTS) or []
        )

    def weather_state(self) -> str | None:
        st = self._state(self.cfg.get(CONF_WEATHER))
        return st.state if st else None

    def weather_blocked(self) -> bool:
        return self.weather_state() in (self.cfg[CONF_BLOCKED] or [])

    def rain_value(self) -> tuple[float | None, str]:
        """Aktueller Niederschlag (mm) und Quelle, falls eine Mess-Quelle vorhanden ist."""
        if self.cfg.get(CONF_RAIN_SENSOR):
            return self._num(self.cfg[CONF_RAIN_SENSOR]), "Regensensor"
        if self.cfg[CONF_BRIGHTSKY] and self._bs_fresh() and isinstance(self.bs.get("precipitation_10"), (int, float)):
            return float(self.bs["precipitation_10"]), f"DWD {self._bs_station or '?'} (10 min)"
        return None, ""

    def restricted_now(self) -> bool | None:
        """True/False aus Messwerten; None = Wetterzustand entscheidet."""
        value, _ = self.rain_value()
        if value is None:
            return None
        now = dt_util.utcnow()
        if value >= float(self.cfg[CONF_RAIN_THRESHOLD]):
            self._last_rain_at = now
            return True
        # Erst nach 15 min ohne Regen wieder weit öffnen – verhindert ständiges Auf und Zu
        return bool(self._last_rain_at and now - self._last_rain_at < RAIN_HOLD)

    def weather_restricted(self) -> bool:
        r = self.restricted_now()
        return (self.weather_state() in (self.cfg[CONF_RESTRICTED] or [])) if r is None else r

    def wind_gust(self) -> tuple[float | None, str]:
        """Aktuelle Böe in km/h und Quelle: gemessen an der DWD-Station, sonst Wetter-Entität."""
        if self.cfg[CONF_BRIGHTSKY] and self._bs_fresh():
            # Bright Sky liefert Wind in km/h (Standard-Einheiten „dwd“)
            for key, label in (("wind_gust_speed_10", "Böe 10 min"), ("wind_gust_speed_60", "Böe 60 min"), ("wind_speed_10", "Wind 10 min")):
                value = self.bs.get(key)
                if isinstance(value, (int, float)):
                    return float(value), f"DWD {self._bs_station or '?'}, {label}"
        st = self._state(self.cfg.get(CONF_WEATHER))
        if st:
            unit = st.attributes.get("wind_speed_unit") or UnitOfSpeed.KILOMETERS_PER_HOUR
            for key, label in (("wind_gust_speed", "Böe"), ("wind_speed", "Wind")):
                try:
                    value = float(st.attributes.get(key))
                    return SpeedConverter.convert(value, unit, UnitOfSpeed.KILOMETERS_PER_HOUR), f"Wetter-Entität, {label}"
                except Exception:  # noqa: BLE001 – fehlender Wert oder unbekannte Einheit
                    continue
        return None, ""

    def storm_now(self) -> bool:
        """Böe gerade über der Schwelle."""
        if not self.cfg[CONF_WIND_ENABLED]:
            return False
        gust, _ = self.wind_gust()
        if gust is not None and gust >= float(self.cfg[CONF_WIND_GUST]):
            self._last_storm_at = dt_util.utcnow()
            return True
        return False

    def storm_blocked(self) -> bool:
        """Sturm jetzt oder vor weniger als 30 min: Automatik öffnet nicht."""
        if self.storm_now():
            return True
        return bool(self.cfg[CONF_WIND_ENABLED] and self._last_storm_at and dt_util.utcnow() - self._last_storm_at < WIND_HOLD)

    async def _check_wind(self) -> None:
        """Sturmschutz: bei Böen über der Schwelle schließen, auch bei Handöffnung oder Automatik aus."""
        if not self.cfg[CONF_WIND_ENABLED]:
            return
        gust, src = self.wind_gust()
        storm = self.storm_now()
        limit = float(self.cfg[CONF_WIND_GUST])
        if storm and not self._storm_logged:
            self._log("WETTER", f"Sturmböen {gust:.0f} km/h ({src}) ab {limit:.0f} km/h – Luke bleibt zu")
        elif not storm and self._storm_logged:
            self._log("WETTER", f"Wind abgeflaut ({gust if gust is not None else '?'} km/h) – Automatik öffnet frühestens in {WIND_HOLD.seconds // 60} min wieder")
        self._storm_logged = storm
        if (
            storm
            and self.is_open()
            and not self._pending_is("close")
            and "verify_close" not in self._timers
            and "verify_close_2" not in self._timers
        ):
            await self._notify("🌪️ Dachluke geschlossen", f"Sturmböen {gust:.0f} km/h ({src}).", critical=True,
                               alexa="Sturmböen. Dachluke wird geschlossen.")
            await self._close("sicherheit", f"Sturmböen {gust:.0f} km/h ({src}) ab {limit:.0f} km/h")
            self._publish()

    # ── Reparaturhinweise ──────────────────────────────────────────────
    def _issue_id(self, key: str) -> str:
        return f"{key}_{self.entry.entry_id}"

    def _issue(self, key: str, active: bool, *, error: bool = False, **placeholders: str) -> None:
        """Hinweis unter Einstellungen → System → Reparaturen anlegen oder entfernen."""
        if active:
            data = {"name": self.entry.title, **placeholders}
            if self.issues.get(key) == data:
                return
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(key),
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR if error else ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders=data,
            )
            self.issues[key] = data
        elif key in self.issues:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(key))
            del self.issues[key]

    def _update_issues(self) -> None:
        """Hinweise entfernen, deren Ursache verschwunden ist."""
        open_ = self.reliable_open()
        if open_ is False:
            self._issue(ISSUE_COVER_NOT_CLOSING, False)
        if open_ is True:
            self._issue(ISSUE_COVER_NOT_OPENING, False)
        if self._pos_from_state(self._state(self.pos_entity)) is not None:
            self._issue(ISSUE_POSITION_MISSING, False)
        if self.humidity() is not None:
            self._issue(ISSUE_HUMIDITY_MISSING, False)

    def _bs_fresh(self) -> bool:
        return bool(self.bs) and self.bs_fetched is not None and dt_util.utcnow() - self.bs_fetched < BS_MAX_AGE

    def outdoor_source(self) -> str:
        if self.cfg[CONF_BRIGHTSKY] and self._bs_fresh():
            return f"DWD {self._bs_station or '?'}"
        return "Wetter-Entität" if self.cfg.get(CONF_WEATHER) else "keine"

    def _weather_attr(self, key: str) -> float | None:
        """Außenwerte: DWD-Messung (Bright Sky), sonst Wetter-Entität."""
        if self.cfg[CONF_BRIGHTSKY] and self._bs_fresh():
            bs_key = {"temperature": "temperature", "humidity": "relative_humidity", "dew_point": "dew_point"}.get(key)
            if bs_key and isinstance(self.bs.get(bs_key), (int, float)):
                return float(self.bs[bs_key])
        st = self._state(self.cfg.get(CONF_WEATHER))
        if not st:
            return None
        try:
            return float(st.attributes.get(key))
        except (TypeError, ValueError):
            return None

    def frost_active(self) -> bool:
        if not self.cfg[CONF_FROST_ENABLED]:
            return False
        temp = self._weather_attr("temperature")
        return temp is not None and temp < float(self.cfg[CONF_FROST_THRESHOLD])

    def alarm_active(self) -> bool:
        st = self._state(self.cfg.get(CONF_ALARM))
        return bool(st and st.state in (self.cfg[CONF_ALARM_STATES] or []))

    def paused(self) -> bool:
        return self.pause_until is not None and dt_util.utcnow() < self.pause_until

    def target(self) -> int:
        return logic.target_position(
            weather_state=self.weather_state(),
            restricted=self.cfg[CONF_RESTRICTED] or [],
            blocked=self.cfg[CONF_BLOCKED] or [],
            frost_active=self.frost_active(),
            pos_normal=int(self.cfg[CONF_POS_NORMAL]),
            pos_restricted=int(self.cfg[CONF_POS_RESTRICTED]),
            pos_frost=int(self.cfg[CONF_FROST_POSITION]),
            restricted_now=self.restricted_now(),
        )

    def _max_minutes(self) -> float:
        return float(self.cfg[CONF_FROST_DURATION] if self.frost_active() else self.cfg[CONF_MAX_OPEN])

    def _manual_minutes(self) -> float:
        minutes = float(self.cfg[CONF_MANUAL_DURATION])
        if self.frost_active():
            minutes = min(minutes, float(self.cfg[CONF_FROST_DURATION]))
        return minutes

    @property
    def status(self) -> str:
        if self.mode == MODE_AUTO:
            return STATUS_AUTO
        if self.mode == MODE_MANUAL:
            return STATUS_MANUAL
        if self.mode == MODE_SECOND:
            return STATUS_SECOND
        if self.humidity() is None or self.position() is None:
            return STATUS_SENSOR
        if not self.enabled:
            return STATUS_DISABLED
        if self.alarm_active():
            return STATUS_ALARM
        if self.weather_blocked() or self.storm_blocked():
            return STATUS_WEATHER
        if self.paused():
            return STATUS_PAUSED
        return STATUS_READY

    def open_blockers(self) -> list[str]:
        """Warum die Automatik gerade nicht öffnen würde (leer = würde öffnen)."""
        reasons = []
        if not self.enabled:
            reasons.append("Automatik aus")
        if self.paused():
            reasons.append("Pause")
        if self.alarm_active():
            reasons.append("Alarm")
        if self.weather_blocked():
            reasons.append("Wetter gesperrt")
        if self.storm_blocked():
            gust, _ = self.wind_gust()
            reasons.append(f"Sturmböen ({gust:.0f} km/h)" if self.storm_now() and gust is not None else "Sturm, Wartezeit")
        if self.position() is None:
            reasons.append("Position unbekannt")
        if self.humidity() is None:
            reasons.append("Feuchte unbekannt")
        if self.cfg[CONF_REQUIRE_LIGHT] and not self.lights_on():
            reasons.append("Licht aus")
        if self.rise is None or self.rise < float(self.cfg[CONF_RISE_THRESHOLD]):
            reasons.append("Steigung unter Schwelle")
        return reasons

    # ════════════════════════════════════════════════════════════════════
    # Ereignisse
    # ════════════════════════════════════════════════════════════════════

    @callback
    def _handle_event(self, event: Event[EventStateChangedData]) -> None:
        eid = event.data["entity_id"]
        new = event.data["new_state"]
        old = event.data["old_state"]
        self.hass.async_create_task(self._dispatch(eid, old, new))

    async def _dispatch(self, eid: str, old: State | None, new: State | None) -> None:
        cfg = self.cfg
        try:
            if eid == cfg[CONF_HUMIDITY_SENSOR]:
                await self._on_humidity(new)
            if eid == cfg.get(CONF_TEMP_SENSOR) or (
                self.has_room and eid in (cfg.get(CONF_ROOM_HUMIDITY), cfg.get(CONF_ROOM_TEMP), cfg.get(CONF_CLIMATE))
            ):
                self._record_room(dt_util.utcnow())
                await self._check_cold()
                await self._evaluate_close()
            if eid == self.pos_entity:
                await self._on_position(old, new)
            if eid in self._buttons():
                await self._on_button(eid, old, new)
            if eid in (cfg.get(CONF_LIGHTS) or []) and new and new.state == STATE_ON:
                await self._evaluate_open("licht")
            if eid == cfg.get(CONF_WEATHER):
                await self._on_weather(old, new)
                await self._check_wind()
            if eid == cfg.get(CONF_RAIN_SENSOR):
                await self._check_rain_change()
            if eid == cfg.get(CONF_ALARM):
                await self._on_alarm()
            if eid == cfg.get(CONF_CONTACT):
                self._schedule_settle()
            if eid == cfg.get(CONF_INDOOR_DEW):
                await self._evaluate_close()
        except Exception:  # noqa: BLE001 – eine fehlerhafte Aktion darf die Steuerung nicht stoppen
            _LOGGER.exception("Fehler bei der Verarbeitung von %s", eid)
        self._publish()

    async def _on_humidity(self, new: State | None) -> None:
        now = dt_util.utcnow()
        value = None
        if new is not None and new.state not in BAD_STATES:
            try:
                value = float(new.state)
            except ValueError:
                value = None
        if value is None:
            self._at("fail_humidity", now + FAILURE_DELAY, self._sensor_failed_humidity)
            return
        self._cancel("fail_humidity")
        self.samples.append((now, value))
        while self.samples and self.samples[0][0] < now - timedelta(minutes=30):
            self.samples.popleft()
        self._record_room(now)
        self.rise = logic.humidity_rise(self.samples, now)
        rise = self.rise or 0.0

        # Dusche erkennen (für die Analyse, unabhängig von der Steuerung)
        if self.shower is None and rise >= float(self.cfg[CONF_SHOWER_DETECT]):
            # Anstieg bei schon laufender Lüftung: keine eigene Dusche, nicht „verpasst“
            venting = self.mode != MODE_IDLE
            self.shower = {"start": now, "max_rise": rise, "light": self.lights_on(), "blockers": set(), "venting": venting}
            if not venting:
                self.counters["showers"] += 1
            self.last_activity = now
            self._at("shower", now + SHOWER_CHECK, self._shower_check)
        if self.shower is not None:
            self.shower["max_rise"] = max(self.shower["max_rise"], rise)
            self.shower["light"] = self.shower["light"] or self.lights_on()
            self.shower["blockers"].update(
                b for b in self.open_blockers() if b != "Steigung unter Schwelle"
            )

        threshold = float(self.cfg[CONF_RISE_THRESHOLD])
        if self.mode == MODE_MANUAL and rise >= threshold:
            # Während einer Handöffnung wird geduscht → Automatik übernimmt
            self.mode = MODE_AUTO
            if self.baseline is None:
                self._set_baselines(now)
            self.peak = value
            self.peak_time = now
            self.shower_end = None
            self.shower_start = logic.rise_start(self.samples, self.shower_baseline)
            self._set_vent_end(self._vent_end_for(now))
            self._log("UEBERNAHME", f"Dusche während Handöffnung erkannt (+{rise:.1f} %/5 min) – Automatik übernimmt")
        elif self.mode == MODE_AUTO and self.opened_at:
            self._track_shower(now, value, rise)

        await self._evaluate_open("steigung")
        await self._evaluate_close()

    async def _on_position(self, old: State | None, new: State | None) -> None:
        now = dt_util.utcnow()
        new_pos = self._parse_pos(new)
        if new_pos is None:
            self._at("fail_position", now + FAILURE_DELAY, self._sensor_failed_position)
            return
        self._cancel("fail_position")
        old_pos = self._parse_pos(old)
        if self._move_start is None:
            self._move_start = now
        self._last_pos_change = now
        if self.mode != MODE_IDLE:
            self.max_pos = max(self.max_pos, new_pos)
        self._schedule_settle()
        if new_pos == 0:
            self._reached_closed = True
        if old_pos is not None and old_pos == new_pos:
            return  # nur Attribut-Update, keine Bewegung
        was_open = old_pos is not None and old_pos > 0
        if new_pos > 0 and not was_open:
            await self._on_opened(new_pos)
        elif new_pos == 0 and was_open:
            await self._on_closed()
        elif new_pos == 0 and old_pos is None and self.mode != MODE_IDLE and not self._pending_is("open"):
            # Sensor war kurz nicht verfügbar und meldet jetzt "zu"
            await self._on_closed()

    _parse_pos = _pos_from_state

    def _pending_is(self, kind: str) -> bool:
        pending = self._pending
        return bool(pending and pending[0] == kind and dt_util.utcnow() <= pending[1])

    def _take_pending(self, kind: str) -> bool:
        pending = self._pending
        if pending and pending[0] == kind and dt_util.utcnow() <= pending[1]:
            self._pending = None
            return True
        return False

    async def _on_opened(self, pos: float) -> None:
        if self._take_pending("open") and self.mode != MODE_IDLE:
            return  # eigene Öffnung, Lüftung läuft bereits
        if self.mode != MODE_IDLE:
            return
        now = dt_util.utcnow()
        if self.alarm_active():
            self._log("ALARM", "Öffnung bei aktivem Alarm – Luke wird wieder geschlossen")
            await self._notify("🚨 Dachluke", "Öffnung bei Alarm verhindert.", critical=True,
                               alexa="Achtung. Dachluke bei Alarm geöffnet. Sie wird geschlossen.")
            await self._close("sicherheit", "Alarm aktiv", from_manual=True)
            return
        if self.storm_now():
            gust, src = self.wind_gust()
            self._log("HAND_AUF", f"Von Hand geöffnet {self._manual_source('open')} bei Sturmböen {gust:.0f} km/h ({src}) – wird geschlossen")
            await self._notify("🌪️ Dachluke", f"Öffnung bei Sturmböen {gust:.0f} km/h verhindert.", critical=True,
                               alexa="Achtung. Sturmböen. Die Dachluke wird wieder geschlossen.")
            await self._close("sicherheit", f"Sturmböen {gust:.0f} km/h ({src})", from_manual=True)
            return
        self.mode = MODE_MANUAL
        self.opened_at = now
        self.last_open = now
        self.pause_until = None
        self._cancel("pause")
        self._set_baselines(now)
        self.peak = None
        self.shower_end = None
        self.shower_start = None
        self.peak_time = None
        self.max_pos = pos
        self._wall_at_open = self.wall_humidity()[0]
        self._prediction_at_open = None
        self.counters["open_manual"] += 1
        if not self.enabled:
            # Automatik aus: Handöffnung bleibt offen. Wetter-Sperre und Alarm schließen weiterhin.
            self.vent_end = None
            self._cancel("vent")
            self._log("HAND_AUF", f"Von Hand geöffnet {self._manual_source('open')} – Automatik aus, kein Zeitlimit")
            return
        self._set_vent_end(now + timedelta(minutes=self._manual_minutes()))
        await self._heating_lower()
        await self._fan_on()
        if self.weather_blocked():
            self.blocked_override = True
            limit = min(int(self.cfg[CONF_POS_RESTRICTED]), int(self.cfg[CONF_FROST_POSITION]) if self.frost_active() else 100)
            if pos > limit:
                await self._command_position(limit)
            dwd = self._dwd_text()
            self._log("HAND_AUF", f"Von Hand geöffnet trotz gesperrtem Wetter ({self.weather_state()}) – auf {limit} % begrenzt")
            await self._notify(
                "⚠️ Dachluke trotz Wetter geöffnet",
                f"Von Hand geöffnet bei {self.weather_state()}. Begrenzt auf {limit} %, schließt nach {self._manual_minutes():.0f} min. {dwd}",
                critical=True,
                alexa=f"Achtung. Dachluke trotz gesperrtem Wetter geöffnet. {dwd} Sie schließt nach {self._manual_minutes():.0f} Minuten.",
            )
        else:
            self._log(
                "HAND_AUF",
                f"Von Hand geöffnet {self._manual_source('open')} (erste Positionsmeldung {pos:.0f} %) – schließt nach "
                f"{self._manual_minutes():.0f} min; {self.context()}",
            )
            await self._notify("🪟 Dachluke geöffnet", f"Von Hand geöffnet. Schließt nach {self._manual_minutes():.0f} min.",
                               alexa="Dachluke von Hand geöffnet.")
        if (self.rise or 0) >= float(self.cfg[CONF_RISE_THRESHOLD]):
            self.mode = MODE_AUTO
            self.peak = self.humidity()
            self.peak_time = now
            self.shower_start = logic.rise_start(self.samples, self.shower_baseline)
            self._set_vent_end(self._vent_end_for(now))
            self._log("UEBERNAHME", "Steigung über Schwelle – Automatik übernimmt die Handöffnung")

    async def _on_closed(self) -> None:
        if self._take_pending("close"):
            return
        if self.mode == MODE_IDLE and not self.heating_lowered:
            return
        self.counters["close_manual"] += 1
        source = self._manual_source("close")
        self._log_balance("von Hand")
        await self._finish_vent("hand")
        self._start_pause()
        self._log("HAND_ZU", f"Von Hand geschlossen {source} – Pause {self.cfg[CONF_PAUSE_DURATION]} min")
        await self._notify("⏸️ Dachluke", f"Von Hand geschlossen, Automatik pausiert für {self.cfg[CONF_PAUSE_DURATION]} min.",
                           alexa="Dachluke geschlossen. Automatik pausiert.")

    async def _on_button(self, eid: str, old: State | None, new: State | None) -> None:
        if new is None or new.state in BAD_STATES:
            return
        if old is None or old.state in BAD_STATES:
            # Entität wird (z. B. nach Neustart) wiederhergestellt – das ist kein Tastendruck
            self._button_seen[eid] = new.state
            return
        if self._button_seen.get(eid) == new.state:
            return  # wiederhergestellter Zustand, kein neuer Tastendruck
        self._button_seen[eid] = new.state
        etype = new.attributes.get("event_type")
        role, remote = self._buttons()[eid]
        short, long_ = etype in EVENT_SHORT, etype in EVENT_LONG
        if short:
            self._button_at[role] = (dt_util.utcnow(), remote)
        if role == "open" and short:
            self._log("TASTE", f"Öffnen kurz{' (Fernbedienung)' if remote else ''}")
            self.pause_until = None
            self._cancel("pause")
            if remote and self.is_open() is False and not self.alarm_active():
                await self._command_manual_open()
        elif role == "open" and long_:
            if not self.enabled:
                self.enabled = True
                self.pause_until = None
                self._cancel("pause")
                self._log("AKTIV", "Automatik per Taste aktiviert")
                await self._notify("🟢 Dachluke-Automatik aktiv", "Per langem Druck aktiviert.", alexa="Dachluke Automatik aktiviert.")
        elif role == "close" and short:
            self._log("TASTE", f"Schließen kurz{' (Fernbedienung)' if remote else ''}")
            self._start_pause()
            if remote and self.is_open():
                await self._close("hand", "Schließen per Fernbedienung", from_manual=True)
        elif role == "close" and long_:
            if self.enabled:
                self.enabled = False
                self._log("DEAKTIV", "Automatik per Taste deaktiviert")
                await self._notify("🔴 Dachluke-Automatik deaktiviert", "Langer Druck auf Öffnen aktiviert sie wieder.",
                                   alexa="Dachluke Automatik deaktiviert.")

    async def _on_weather(self, old: State | None, new: State | None) -> None:
        if not self.is_open() or new is None:
            return
        blocked = self.cfg[CONF_BLOCKED] or []
        if new.state in blocked:
            if self.blocked_override and old is not None and old.state in blocked:
                return
            self._log("WETTER", f"Wetter gesperrt ({new.state}) – Luke geschlossen")
            await self._notify("🌪️ Dachluke geschlossen", f"Wetter gesperrt ({new.state}).", critical=True,
                               alexa="Wetter gesperrt. Dachluke geschlossen.")
            await self._close("sicherheit", f"Wetter {new.state}")
            return
        old_s = old.state if old else "?"
        await self._correct_position(f"Wetter {old_s} → {new.state}")

    async def _correct_position(self, why: str) -> None:
        """Öffnungsweite an Wetter/Regen anpassen, ohne die Lüftung neu zu starten."""
        if not self.is_open() or self.mode not in (MODE_AUTO, MODE_SECOND):
            return
        target = self.target()
        pos = self.position() or 0
        if target > 0 and abs(pos - target) >= float(self.cfg[CONF_POS_TOLERANCE]):
            await self._command_position(target)
            self._log("WETTER", f"{why}: Position {pos:.0f} % → {target} % – Öffnungsweite: {self.position_reason()}")
            await self._notify("🪟 Dachluke angepasst", f"{why}. Position {pos:.0f} % → {target} %.",
                               critical=True, alexa=f"Neues Wetter. Dachluke auf {target} Prozent angepasst.")

    async def _check_rain_change(self) -> None:
        now = self.restricted_now()
        if now is None or now == self._last_restricted:
            self._last_restricted = now
            return
        self._last_restricted = now
        value, src = self.rain_value()
        await self._correct_position(f"{'Regen' if now else 'Regen vorbei'} ({src} {value or 0:.1f} mm)")

    @callback
    def _consistency_tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self._consistency_check())

    async def _consistency_check(self) -> None:
        """Sicherheitsnetz: Zustand der Luke und interne Lüftung müssen zusammenpassen."""
        now = dt_util.utcnow()
        await self._check_rain_change()  # Regen-Haltezeit läuft ab
        await self._check_wind()
        await self._check_cold()
        self._update_issues()
        if self.heating_lowered and self.mode == MODE_IDLE:
            await self._heating_restore()  # Thermostat war beim Schließen nicht erreichbar
        busy = (
            self._moving()
            or self._pending_is("open")
            or self._pending_is("close")
            or "verify_close" in self._timers
            or "verify_close_2" in self._timers
            or (self._last_pos_change and now - self._last_pos_change < SETTLED_FOR)
        )
        if busy:
            return
        open_ = self.reliable_open()  # nur echte Positionsmeldung, kein Ersatzwert
        if open_ and self.mode == MODE_IDLE:
            self._log("KORREKTUR", "Luke offen, aber keine Lüftung bekannt – als Handöffnung übernommen")
            await self._on_opened(self.position() or 0)
            self._publish()
        elif open_ is False and self.mode != MODE_IDLE:
            if self.max_pos <= 0:
                self._log("FEHLER", "Luke hat sich nach dem Öffnungsbefehl nicht bewegt – Lüftung beendet")
                self._issue(ISSUE_COVER_NOT_OPENING, True, error=True)
                await self._notify("⚠️ Dachluke", "Die Luke hat sich nicht geöffnet. Bitte CCU und Antrieb prüfen.",
                                   critical=True, alexa="Achtung. Die Dachluke hat sich nicht geöffnet.")
            else:
                self._log("KORREKTUR", "Luke zu, aber Lüftung noch aktiv – Lüftung beendet")
            await self._finish_vent("korrektur")
            self._publish()

    async def _check_cold(self) -> None:
        """Auskühlschutz: Lüftung beenden, wenn der Raum unter die Mindesttemperatur fällt."""
        if not self.cfg[CONF_COLD_ENABLED] or self.mode not in (MODE_AUTO, MODE_SECOND) or not self.opened_at:
            return
        if dt_util.utcnow() - self.opened_at < timedelta(minutes=float(self.cfg[CONF_MIN_OPEN])):
            return
        temp = self.room_temperature()
        limit = float(self.cfg[CONF_COLD_MIN])
        if temp is not None and temp < limit:
            await self._close("auskuehlung", f"Raum kühlt aus: {temp:.1f} °C unter {limit:.1f} °C")

    async def _verify_close(self, _now: datetime) -> None:
        """Nach dem Schließbefehl prüfen, ob die Luke wirklich zu ist."""
        if self._reached_closed or self.reliable_open() is not True:
            return
        if self._moving():
            self._at("verify_close", dt_util.utcnow() + timedelta(seconds=30), self._verify_close)
            return
        self._log("FEHLER", f"Luke steht nach dem Schließbefehl noch bei {self.position() or 0:.0f} % – zweiter Versuch")
        self._pending = ("close", dt_util.utcnow() + timedelta(seconds=PENDING_SECONDS))
        await self._call("cover", "close_cover", {"entity_id": self.cfg[CONF_COVER]})
        self._at("verify_close_2", dt_util.utcnow() + VERIFY_CLOSE_2, self._verify_close_2)

    async def _verify_close_2(self, _now: datetime) -> None:
        if self._reached_closed or self.reliable_open() is not True:
            return
        self._log("FEHLER", f"Luke schließt nicht (steht bei {self.position() or 0:.0f} %) – bitte prüfen")
        self._issue(ISSUE_COVER_NOT_CLOSING, True, error=True, position=f"{self.position() or 0:.0f}")
        await self._notify("⚠️ Dachluke schließt nicht",
                           f"Die Luke steht nach zwei Schließbefehlen noch bei {self.position() or 0:.0f} %. Bitte prüfen.",
                           critical=True, alexa="Achtung. Die Dachluke schließt nicht.")

    @callback
    def _bs_tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self._fetch_brightsky())

    async def _fetch_brightsky(self) -> None:
        """DWD-Messwerte der nächsten Station über Bright Sky (frei, ohne Schlüssel)."""
        # Auf ca. 1 km gerundet: reicht für die Stationssuche, verrät nicht die genaue Adresse
        params = {"lat": round(self.hass.config.latitude, 2), "lon": round(self.hass.config.longitude, 2)}
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(BRIGHTSKY_URL, params=params, timeout=20) as resp:
                resp.raise_for_status()
                data = await resp.json()
            weather = data.get("weather") or {}
            if isinstance(weather, list):
                weather = weather[-1] if weather else {}
            if not isinstance(weather, dict) or "temperature" not in weather:
                raise ValueError("unerwartete Antwort")
            sources = data.get("sources") or []
            main = next((s for s in sources if s.get("id") == weather.get("source_id")), sources[0] if sources else {})
            station = main.get("station_name") or "?"
            dist = main.get("distance")
            label = f"{station}, {dist / 1000:.0f} km" if isinstance(dist, (int, float)) else station
        except Exception as err:  # noqa: BLE001 – Netz, JSON, Format: immer auf Wetter-Entität zurückfallen
            if not self._bs_failed:
                self._log("WETTERQUELLE", f"DWD-Messwerte (Bright Sky) nicht verfügbar ({err}) – nutze Wetter-Entität")
                self._bs_failed_since = dt_util.utcnow()
            self._bs_failed = True
            if self._bs_failed_since and dt_util.utcnow() - self._bs_failed_since >= BS_ISSUE_AFTER:
                self._issue(ISSUE_BRIGHTSKY, True, reason=str(err)[:200] or type(err).__name__)
            self._publish()
            return
        self.bs = weather
        self.bs_fetched = dt_util.utcnow()
        if self._bs_failed or label != self._bs_station:
            self._log(
                "WETTERQUELLE",
                f"DWD-Messwerte von {label}: {weather.get('temperature')} °C, {weather.get('relative_humidity')} %, "
                f"Niederschlag 10 min {weather.get('precipitation_10')} mm",
            )
        self._bs_failed = False
        self._bs_failed_since = None
        self._issue(ISSUE_BRIGHTSKY, False)
        self._bs_station = label
        await self._check_rain_change()
        await self._check_wind()
        self._publish()

    async def _on_alarm(self) -> None:
        if self.alarm_active() and self.is_open() is not False:
            self._log("ALARM", "Alarm aktiv – Luke geschlossen")
            await self._notify("🚨 Dachluke geschlossen", "Alarm aktiv – Luke geschlossen.", critical=True,
                               alexa="Alarm aktiviert. Dachluke geschlossen.")
            await self._close("sicherheit", "Alarm")

    # ════════════════════════════════════════════════════════════════════
    # Entscheidungen
    # ════════════════════════════════════════════════════════════════════

    async def _evaluate_open(self, trigger: str) -> None:
        if self.mode != MODE_IDLE or self.is_open() is not False:
            return
        if self.open_blockers():
            return
        target = self.target()
        if target <= 0:
            return
        now = dt_util.utcnow()
        self.mode = MODE_AUTO
        self.opened_at = now
        self.last_open = now
        self.blocked_override = False
        self._set_baselines(now)
        self.peak = self.humidity()
        self.peak_time = now
        self.shower_end = None
        self.shower_start = logic.rise_start(self.samples, self.shower_baseline)
        self.max_pos = 0.0
        self.counters["open_auto"] += 1
        self._set_vent_end(now + timedelta(minutes=self._max_minutes()))
        self._at("min_open", now + timedelta(minutes=float(self.cfg[CONF_MIN_OPEN])), self._min_open_elapsed)
        self._cancel("second_wait")
        self.second_at = None
        await self._command_position(target)
        await self._heating_lower()
        await self._fan_on()
        hum = self.humidity()
        frost = " ❄️ Frost" if self.frost_active() else ""
        start = self.shower_start
        since = f", Anstieg seit {dt_util.as_local(start).strftime('%H:%M')}" if start else ""
        self._wall_at_open = self.wall_humidity()[0]
        self._prediction_at_open = self.vent_prediction()
        extra = []
        if self._wall_at_open is not None:
            extra.append(f"Wandfeuchte {self._wall_at_open:.0f} %")
        if self._prediction_at_open is not None:
            extra.append(f"Vorhersage Lüftdauer {self._prediction_at_open:.0f} min")
        self._extra_open = ("; " + ", ".join(extra)) if extra else ""
        self._log(
            "AUTO_AUF",
            f"Automatisch geöffnet auf {target} % – Öffnungsweite: {self.position_reason()} "
            f"(Auslöser {trigger}, +{self.rise or 0:.1f} %/5 min, Basis {self.baseline or 0:.0f} %"
            f"{f' / {self.baseline_ah:.1f} g/m³' if self.baseline_ah is not None else ''}{since}); "
            f"{self._target_text()}{self._extra_open}; {self.context()}",
        )
        await self._notify("🪟 Dachluke geöffnet", f"{target} %, Steigung +{self.rise:.1f} %/5 min, rF {hum:.0f} %.{frost}",
                           alexa="Dachluke geöffnet. Lüftung aktiv.")

    async def _evaluate_close(self) -> None:
        if self.mode != MODE_AUTO or not self.opened_at:
            return
        if dt_util.utcnow() - self.opened_at < timedelta(minutes=float(self.cfg[CONF_MIN_OPEN])):
            return
        if self.shower_end is None:
            # Solange geduscht wird, nicht wegen Feuchte schließen. Der Raumsensor
            # reagiert oft erst Minuten später und läge sonst noch am Ausgangswert.
            return
        indoor_dew = self._num(self.cfg.get(CONF_INDOOR_DEW))
        target_rh, target_ah = self.close_targets()
        reason = logic.close_reason(
            humidity=self.room_humidity(),
            baseline=target_rh,
            close_offset=float(self.cfg[CONF_CLOSE_OFFSET]),
            abs_humidity=self.abs_humidity(),
            baseline_ah=target_ah,
            ah_offset=float(self.cfg[CONF_CLOSE_AH_OFFSET]),
            close_abs=float(self.cfg[CONF_CLOSE_ABS]),
            indoor_dew=indoor_dew,
            outdoor_dew=self._weather_attr("dew_point"),
            dew_offset=float(self.cfg[CONF_DEW_OFFSET]),
            dew_enabled=bool(self.cfg[CONF_DEW_ENABLED]),
        )
        if reason:
            dry, dry_text = self.shower_dry()
            if not dry:
                return  # Raum schon ok, aber über der Dusche steht noch feuchte Luft
            if reason == "absolut":
                text = (
                    f"Absolute Feuchte {self.abs_humidity() or 0:.1f} g/m³ wieder nahe Bezugswert {target_ah or 0:.1f} g/m³ "
                    f"({self.target_source(absolute=True)})"
                )
            elif reason == "basis":
                text = (
                    f"{'Raumfeuchte' if self.has_room else 'Feuchte'} {self.room_humidity() or 0:.0f} % wieder nahe "
                    f"Bezugswert {target_rh or 0:.0f} % ({self.target_source(absolute=False)})"
                )
            elif reason == "schwelle":
                text = f"{'Raumfeuchte' if self.has_room else 'Feuchte'} {self.room_humidity() or 0:.0f} % unter {float(self.cfg[CONF_CLOSE_ABS]):.0f} %"
            else:
                text = f"Taupunkt innen {indoor_dew} °C unter außen + Offset"
            if dry_text:
                text += f"; {dry_text}"
            await self._close("feuchte", text)

    async def _close(self, kind: str, text: str, *, from_manual: bool = False) -> None:
        """Luke schließen. kind: feuchte | timer | nachlueften | sicherheit | hand."""
        was_mode = self.mode
        self._pending = ("close", dt_util.utcnow() + timedelta(seconds=PENDING_SECONDS))
        self._reached_closed = False
        await self._call("cover", "close_cover", {"entity_id": self.cfg[CONF_COVER]})
        self._at("verify_close", dt_util.utcnow() + VERIFY_CLOSE, self._verify_close)
        counter = {
            "feuchte": "close_humidity",
            "timer": "close_timer",
            "stagnation": "close_stall",
            "auskuehlung": "close_cold",
            "sicherheit": "close_safety",
            "hand": "close_manual",
        }.get(kind)
        if counter and (was_mode != MODE_IDLE or kind == "sicherheit"):
            self.counters[counter] += 1
        if was_mode != MODE_IDLE:
            self._log_balance(kind)
        await self._finish_vent(kind)
        if kind != "hand":
            self._log("ZU", f"Geschlossen: {text}")
        if kind in ("feuchte", "timer", "stagnation", "auskuehlung") and not from_manual:
            await self._notify("✅ Dachluke geschlossen", text,
                               critical=kind == "timer",
                               alexa="Lüftung abgeschlossen. Dachluke geschlossen.")
        if kind in ("feuchte", "timer", "stagnation") and was_mode == MODE_AUTO:
            self._schedule_second_vent()

    def _estimate_shower(self) -> None:
        """Geschätzte Duschdauer, auch wenn kein Duschende erkannt wurde."""
        if self.shower_start and self.peak_time and self.peak_time >= self.shower_start:
            self.last_shower_minutes = round((self.peak_time - self.shower_start).total_seconds() / 60, 1)

    def _log_balance(self, kind: str) -> None:
        """Bilanz einer Lüftung für die spätere Auswertung."""
        if not self.opened_at:
            return
        if self.shower_end is None and self.mode == MODE_AUTO:
            self._estimate_shower()
        now = dt_util.utcnow()
        minutes = (now - self.opened_at).total_seconds() / 60
        after = (now - self.shower_end).total_seconds() / 60 if self.shower_end else None
        hum, ah = self.room_humidity(), self.abs_humidity()
        parts = [
            f"Grund {kind}",
            f"offen {minutes:.0f} min" + (f" (davon {after:.0f} nach Duschende)" if after is not None else ""),
            f"max. {self.max_pos:.0f} %",
        ]
        if self.has_room:
            parts += [
                f"Dusche: Basis {self._fmt(self.shower_baseline, ' %')}, Höchstwert {self._fmt(self.peak, ' %')}, jetzt {self._fmt(self.humidity(), ' %')}",
                f"Raum: Basis {self._fmt(self.baseline, ' %')}, Höchstwert {self._fmt(self.room_peak, ' %')}, jetzt {self._fmt(hum, ' %')}",
            ]
        else:
            parts += [
                f"Höchstwert {self._fmt(self.peak, ' %')}",
                f"Basis {self._fmt(self.baseline, ' %')} → jetzt {self._fmt(hum, ' %')}",
            ]
        if ah is not None or self.baseline_ah is not None:
            parts.append(f"absolut {self._fmt(self.baseline_ah, '', 1)} → {self._fmt(ah, ' g/m³', 1)}")
        if self.last_shower_minutes is not None and self.shower_start:
            parts.append(f"Duschen ca. {self.last_shower_minutes:.0f} min" + ("" if self.shower_end else " (kein Duschende erkannt)"))
        parts.append(self._target_text())
        wall, t_crit = self.wall_humidity()
        if wall is not None:
            start = f"{self._wall_at_open:.0f} % → " if self._wall_at_open is not None else ""
            parts.append(f"Wandfeuchte {start}{wall:.0f} % (kälteste Stelle {t_crit:.1f} °C)")
        if self._prediction_at_open is not None:
            parts.append(f"Vorhersage Lüftdauer {self._prediction_at_open:.0f} min, tatsächlich {minutes:.0f} min")
        parts.append(self.context())
        self._log("BILANZ", "; ".join(parts))

    async def _finish_vent(self, kind: str) -> None:
        now = dt_util.utcnow()
        if self.opened_at:
            self.last_duration = round((now - self.opened_at).total_seconds() / 60, 1)
        self.mode = MODE_IDLE
        self.opened_at = None
        self.cap_base = None
        self.vent_end = None
        self.blocked_override = False
        self.peak = None
        self.shower_end = None
        self.shower_start = None
        self.peak_time = None
        self.baseline_ah = None
        self.room_peak = None
        self.last_activity = now
        for key in ("vent", "min_open", "stall"):
            self._cancel(key)
        await self._heating_restore()
        await self._fan_off()

    # ════════════════════════════════════════════════════════════════════
    # Zeitgesteuerte Abläufe
    # ════════════════════════════════════════════════════════════════════

    def _cap_end(self) -> datetime:
        """Harte Obergrenze: ab Öffnen, bei einer neuen Dusche während der Lüftung ab deren Beginn."""
        base = max(b for b in (self.opened_at, self.cap_base) if b is not None)
        return base + timedelta(minutes=float(self.cfg[CONF_HARD_CAP]))

    def _vent_end_for(self, now: datetime) -> datetime:
        """Ende der Lüftung: jetzt + maximale Dauer, höchstens bis zur Obergrenze."""
        end = now + timedelta(minutes=self._max_minutes())
        if self.opened_at:
            end = min(end, self._cap_end())
        return end

    def _track_shower(self, now: datetime, value: float, rise: float) -> None:
        """Duschende erkennen: Die maximale Dauer zählt erst, wenn die Feuchte
        vom Höchstwert merklich fällt. Bis dahin wird die Lüftung verlängert."""
        threshold = float(self.cfg[CONF_RISE_THRESHOLD])
        drop = float(self.cfg[CONF_SHOWER_END_DROP])
        if self.shower_end is not None and rise >= threshold:
            # Kurz nach dem Duschende wieder steigend: dieselbe Dusche (z. B. Wasser kurz aus)
            continued = now - self.shower_end <= SHOWER_RESUME
            self.shower_end = None
            self._cancel("stall")
            self.peak = value
            self.peak_time = now
            if not continued or self.shower_start is None:
                self.shower_start = now
            if not continued:
                # zweite Person: eigene Dusche, Obergrenze zählt neu
                self.counters["showers"] += 1
                self.cap_base = now
            self._log("DUSCHE", f"Feuchte steigt wieder (+{rise:.1f} %/5 min) – "
                      + ("Dusche läuft weiter" if continued else "neue Dusche") + ", Lüftung läuft weiter")
        if self.peak is None or value > self.peak:
            self.peak = value
        if self.shower_end is None and value >= self.peak - 1:
            self.peak_time = now  # noch am Höchstwert
        if self.shower_end is None:
            if value <= self.peak - drop:
                if self.peak_time and now - self.peak_time > timedelta(minutes=3):
                    # Gesättigter Sensor meldet am Höchstwert nichts mehr. Der erste
                    # fallende Wert kommt kurz nach dem Duschende.
                    self.peak_time = now - timedelta(minutes=1)
                self.shower_end = now
                self._set_vent_end(self._vent_end_for(now))
                self._schedule_stall_check(now)
                duration = ""
                if self.shower_start and self.peak_time and self.peak_time >= self.shower_start:
                    self._estimate_shower()
                    duration = (
                        f"; Duschen geschätzt {self.last_shower_minutes:.0f} min "
                        f"({dt_util.as_local(self.shower_start).strftime('%H:%M')}–{dt_util.as_local(self.peak_time).strftime('%H:%M')})"
                    )
                self._log(
                    "DUSCHE_ENDE",
                    f"Feuchte fällt vom Höchstwert {self.peak:.0f} % auf {value:.0f} % – Nachlüften höchstens "
                    f"{self._max_minutes():.0f} min{duration}",
                )
            else:
                new_end = self._vent_end_for(now)
                if self.vent_end is None or new_end > self.vent_end:
                    self._set_vent_end(new_end)

    def _schedule_stall_check(self, base: datetime) -> None:
        if not self.cfg[CONF_STALL_ENABLED]:
            return
        self._at("stall", base + timedelta(minutes=float(self.cfg[CONF_STALL_MINUTES])), self._stall_check)

    async def _stall_check(self, _now: datetime) -> None:
        """Nach dem Duschen: fällt die Feuchte kaum noch, bringt Lüften nichts mehr."""
        if self.mode != MODE_AUTO or self.shower_end is None:
            return
        now = dt_util.utcnow()
        minutes = float(self.cfg[CONF_STALL_MINUTES])
        if self._stalled(now):
            minutes_txt = f"{minutes:.0f} min"
            hum = self.room_humidity()
            await self._close(
                "stagnation",
                f"Trocknung stagniert: in {minutes_txt} kaum Abfall ({self._drop_text(now)}; jetzt {hum or 0:.0f} %)",
            )
            return
        self._at("stall", now + timedelta(minutes=2), self._stall_check)

    def _drops(self, now: datetime) -> tuple[float | None, float | None]:
        minutes = float(self.cfg[CONF_STALL_MINUTES])
        room = logic.humidity_drop(self.room_samples, now, minutes)
        shower = logic.humidity_drop(self.samples, now, minutes) if self.has_room else None
        return room, shower

    def _drop_text(self, now: datetime) -> str:
        room, shower = self._drops(now)
        txt = f"{'Raum' if self.has_room else 'Feuchte'} −{max(room or 0, 0):.1f} %"
        if self.has_room:
            txt += f", Dusche −{max(shower or 0, 0):.1f} %"
        return txt

    def _stalled(self, now: datetime) -> bool:
        """Stagnation nur, wenn KEIN Sensor mehr nennenswert fällt."""
        delta = float(self.cfg[CONF_STALL_DELTA])
        room, shower = self._drops(now)
        if room is None:
            return False
        if room >= delta:
            return False
        return not (self.has_room and shower is not None and shower >= delta)

    def _set_vent_end(self, when: datetime) -> None:
        self.vent_end = when
        self._at("vent", when, self._vent_elapsed)

    async def _vent_elapsed(self, _now: datetime) -> None:
        now = dt_util.utcnow()
        if self.mode == MODE_AUTO and self.shower_end is None and self.opened_at:
            # Sensoren melden gleichbleibende Werte oft nicht als Änderung.
            # Steht die Feuchte noch am Höchstwert, wird weiter geduscht.
            hum = self.humidity()
            cap = self._cap_end()
            drop = float(self.cfg[CONF_SHOWER_END_DROP])
            if hum is not None and self.peak is not None and hum > self.peak - drop and now < cap - timedelta(seconds=30):
                self._set_vent_end(self._vent_end_for(now))
                return
        if (
            self.mode == MODE_AUTO
            and self.shower_end is not None
            and self.opened_at
            and self.cfg[CONF_EXTEND]
            and now < self._cap_end() - timedelta(minutes=1)
            and not self._stalled(now)
        ):
            # Noch nicht trocken und es geht voran: weiterlüften (Obergrenze und Stagnation begrenzen)
            new_end = min(
                now + timedelta(minutes=5),
                self._cap_end(),
            )
            self._set_vent_end(new_end)
            self._log("VERLAENGERT", f"Noch feucht, Trocknung läuft ({self._drop_text(now)}) – 5 min länger")
            return
        if self.mode == MODE_SECOND:
            await self._close("nachlueften", "Zweites Nachlüften beendet")
        elif self.mode in (MODE_AUTO, MODE_MANUAL):
            minutes = (dt_util.utcnow() - self.opened_at).total_seconds() / 60 if self.opened_at else 0
            await self._close("timer", f"Maximale Öffnungsdauer erreicht ({minutes:.0f} min)")

    async def _min_open_elapsed(self, _now: datetime) -> None:
        await self._evaluate_close()

    def _start_pause(self) -> None:
        self.pause_until = dt_util.utcnow() + timedelta(minutes=float(self.cfg[CONF_PAUSE_DURATION]))
        self._at("pause", self.pause_until, self._pause_elapsed)

    async def _pause_elapsed(self, _now: datetime) -> None:
        self.pause_until = None
        self._log("PAUSE_ENDE", "Pause abgelaufen – Automatik wieder bereit")

    def _schedule_second_vent(self) -> None:
        if not self.cfg[CONF_SECOND_ENABLED]:
            return
        self.second_at = dt_util.utcnow() + timedelta(minutes=float(self.cfg[CONF_SECOND_WAIT]))
        self._at("second_wait", self.second_at, self._second_wait_elapsed)

    async def _second_wait_elapsed(self, _now: datetime) -> None:
        self.second_at = None
        hum = self.room_humidity()
        if (
            hum is not None
            and hum > float(self.cfg[CONF_SECOND_THRESHOLD])
            and self.mode == MODE_IDLE
            and self.is_open() is False
            and self.enabled
            and not self.paused()
            and not self.alarm_active()
            and not self.weather_blocked()
            and not self.storm_blocked()
        ):
            target = self.target()
            now = dt_util.utcnow()
            self.mode = MODE_SECOND
            self.opened_at = now
            self._set_vent_end(now + timedelta(minutes=float(self.cfg[CONF_SECOND_DURATION])))
            await self._command_position(target)
            if self.cfg[CONF_SECOND_HEATING]:
                await self._heating_lower()
            await self._fan_on()
            self._log("NACHLUEFTEN", f"Zweites Nachlüften bei {hum:.0f} % für {self.cfg[CONF_SECOND_DURATION]} min auf {target} % – Öffnungsweite: {self.position_reason()}; {self.context()}")
            await self._notify("🔄 Dachluke", f"Zweites Nachlüften, Restfeuchte {hum:.0f} %.",
                               alexa=f"Zweites Nachlüften. Restfeuchte {hum:.0f} Prozent.")
        else:
            self._log("NACHLUEFTEN", f"Zweites Nachlüften nicht nötig oder gesperrt (rF {hum if hum is not None else '?'} %)")

    async def _shower_check(self, _now: datetime) -> None:
        shower, self.shower = self.shower, None
        if not shower:
            return
        if shower.get("venting"):
            self._log("DUSCHE", f"Weiterer Feuchte-Anstieg während der Lüftung (Steigung max. +{shower['max_rise']:.1f} %/5 min) – nicht als eigene Dusche gezählt")
            return
        opened = self.last_open is not None and self.last_open >= shower["start"] - timedelta(minutes=2)
        if opened:
            self._log("DUSCHE", f"Dusche erkannt, Luke geöffnet (Steigung max. +{shower['max_rise']:.1f} %/5 min)")
            return
        reasons = sorted(shower["blockers"])
        if shower["max_rise"] < float(self.cfg[CONF_RISE_THRESHOLD]):
            reasons.insert(0, f"Steigung max. {shower['max_rise']:.1f} < Schwelle {float(self.cfg[CONF_RISE_THRESHOLD]):.0f}")
        if not shower["light"]:
            reasons.append("Licht war aus")
        self.counters["showers_missed"] += 1
        self._log("DUSCHE_VERPASST", "Dusche ohne Öffnen: " + ("; ".join(reasons) or "Grund unklar"))

    async def _sensor_failed_humidity(self, _now: datetime) -> None:
        self.counters["sensor_failures"] += 1
        self._log("AUSFALL", "Feuchtesensor seit 5 min nicht verfügbar")
        self._issue(ISSUE_HUMIDITY_MISSING, True, entity=str(self.cfg[CONF_HUMIDITY_SENSOR]))
        await self._notify("⚠️ Dachluke", "Feuchtesensor nicht verfügbar.", critical=True)

    async def _sensor_failed_position(self, _now: datetime) -> None:
        self.counters["sensor_failures"] += 1
        self._log("AUSFALL", f"Position der Luke ({self.pos_entity}) seit 5 min nicht verfügbar – Automatik öffnet nicht")
        self._issue(ISSUE_POSITION_MISSING, True, error=True, entity=self.pos_entity)
        await self._notify("⚠️ Dachluke", "Positionssensor nicht verfügbar. Automatisches Öffnen gesperrt.", critical=True,
                           alexa="Achtung. Dachluke Positionssensor ausgefallen.")

    def _schedule_settle(self) -> None:
        """Erst auswerten, wenn die Luke steht: Position eine Weile unverändert und Cover fährt nicht."""
        wait = max(float(self.cfg[CONF_CONTACT_GRACE]), 10.0)
        self._cancel("contact_confirm")
        self._at("settle", dt_util.utcnow() + timedelta(seconds=wait), self._position_settled)

    def _moving(self) -> bool:
        cover = self._state(self.cfg[CONF_COVER])
        return bool(cover and cover.state in ("opening", "closing"))

    async def _position_settled(self, _now: datetime) -> None:
        now = dt_util.utcnow()
        if self._moving():
            self._at("settle", now + SETTLE_POLL, self._position_settled)
            return
        pos = self.position()
        if pos is not None and pos != self._settled_pos:
            travel = ""
            if self._move_start and self._last_pos_change and self._last_pos_change > self._move_start:
                travel = f" (Positionsmeldungen über {(self._last_pos_change - self._move_start).total_seconds():.0f} s)"
            contact = self._state(self.cfg.get(CONF_CONTACT))
            ctext = f", Kontakt {contact.state}" if contact else ""
            self._log("ENDLAGE", f"Luke steht bei {pos:.0f} %{travel}{ctext}")
            self._settled_pos = pos
        self._move_start = None
        if self._contact_mismatch():
            # Kontakte melden teils verzögert: erst nach einer Bestätigung warnen
            self._at("contact_confirm", now + CONFIRM_DELAY, self._contact_check)

    def _contact_mismatch(self) -> bool:
        contact = self._state(self.cfg.get(CONF_CONTACT))
        pos = self.position()
        if contact is None or contact.state in BAD_STATES or pos is None:
            return False
        return (pos > 0) != (contact.state == STATE_ON)

    async def _contact_check(self, _now: datetime) -> None:
        if self._moving() or not self._contact_mismatch():
            return
        contact = self._state(self.cfg.get(CONF_CONTACT))
        pos = self.position() or 0
        self._log("WIDERSPRUCH", f"Position {pos:.0f} % aber Kontakt {contact.state} (über {CONFIRM_DELAY.seconds} s nach Stillstand)")
        await self._notify("⚠️ Dachluke Sensor-Widerspruch",
                           f"Positionssensor {pos:.0f} %, Fensterkontakt {contact.state}. Bitte prüfen.",
                           critical=True, alexa="Achtung. Dachluke Sensorfehler.")

    # ════════════════════════════════════════════════════════════════════
    # Aktionen
    # ════════════════════════════════════════════════════════════════════

    def _supports_position(self) -> bool:
        cover = self._state(self.cfg[CONF_COVER])
        if cover is None or "supported_features" not in cover.attributes:
            return True  # unbekannt: Position senden
        return bool(int(cover.attributes["supported_features"] or 0) & CoverEntityFeature.SET_POSITION)

    async def _cover_to(self, position: int) -> None:
        """Position anfahren; Covers ohne Positionssteuerung werden nur ganz geöffnet."""
        if self._supports_position():
            await self._call("cover", "set_cover_position", {"entity_id": self.cfg[CONF_COVER], "position": int(position)})
        elif position > 0:
            await self._call("cover", "open_cover", {"entity_id": self.cfg[CONF_COVER]})
        else:
            await self._call("cover", "close_cover", {"entity_id": self.cfg[CONF_COVER]})

    async def _command_position(self, position: int) -> None:
        self._pending = ("open", dt_util.utcnow() + timedelta(seconds=PENDING_SECONDS))
        await self._cover_to(int(position))

    async def _command_manual_open(self) -> None:
        """Öffnen per Fernbedienung ohne Direktverknüpfung."""
        await self._cover_to(self.target() or int(self.cfg[CONF_POS_RESTRICTED]))

    async def _heating_lower(self) -> None:
        climate = self.cfg.get(CONF_CLIMATE)
        if not (self.cfg[CONF_HEATING_ENABLED] and climate) or self.heating_lowered:
            return
        st = self._state(climate)
        if st is None or st.state in BAD_STATES:
            return
        if self.heating_ineffective:
            return  # Thermostat regelt beim offenen Fenster selbst (siehe HEIZUNG-Hinweis)
        current = st.attributes.get("temperature")
        self.saved_setpoint = float(current) if current is not None else None
        self.heating_lowered = True
        await self._call("climate", "set_temperature", {"entity_id": climate, "temperature": float(self.cfg[CONF_HEATING_VENT_TEMP])})
        self._at("heat_check", dt_util.utcnow() + HEAT_CHECK, self._heat_check)

    async def _heat_check(self, _now: datetime) -> None:
        """Übernimmt das Thermostat die Lüft-Temperatur? HmIP-Thermostate mit verknüpftem
        Fensterkontakt nutzen ihre eigene Fenster-auf-Temperatur und ignorieren den Wert."""
        if not self.heating_lowered:
            return
        st = self._state(self.cfg.get(CONF_CLIMATE))
        try:
            now_set = float(st.attributes.get("temperature")) if st else None
        except (TypeError, ValueError):
            now_set = None
        vent = float(self.cfg[CONF_HEATING_VENT_TEMP])
        if now_set is not None and abs(now_set - vent) > 0.4:
            self.heating_ineffective = True
            self._issue(ISSUE_HEATING_INEFFECTIVE, True, setpoint=f"{now_set:.1f}", vent=f"{vent:.1f}")
            self.heating_lowered = False  # nichts zurückstellen, sonst würde der eigene Wert überschrieben
            self.saved_setpoint = None
            self._log(
                "HEIZUNG",
                f"Thermostat übernimmt die Lüft-Temperatur {vent:.1f} °C nicht (Soll {now_set:.1f} °C) – vermutlich eigene "
                "Fenster-auf-Funktion. Die Integration greift bis zum nächsten Neustart nicht mehr in die Heizung ein.",
            )
            self._publish()

    async def _fan_on(self) -> None:
        """Lüfter ergänzt die offene Luke. Lief er schon, bleibt er unangetastet."""
        fan = self.cfg.get(CONF_FAN)
        if not (fan and self.cfg[CONF_FAN_CONTROL]) or self.fan_started:
            return
        st = self._state(fan)
        if st is None or st.state in BAD_STATES:
            self._log("FEHLER", f"Lüfter {fan} nicht verfügbar – nicht eingeschaltet")
            return
        if st.state == STATE_ON:
            self._log("LUEFTER", "Lüfter lief bereits – bleibt an, wird später nicht ausgeschaltet")
            return
        await self._call(fan.split(".", 1)[0], "turn_on", {"entity_id": fan})
        self.fan_started = True
        self._log("LUEFTER", "Lüfter eingeschaltet (Luke offen)")

    async def _fan_off(self) -> None:
        """Nur ausschalten, wenn die Integration ihn eingeschaltet hat."""
        fan = self.cfg.get(CONF_FAN)
        if not self.fan_started or not fan:
            self.fan_started = False
            return
        self.fan_started = False
        st = self._state(fan)
        if st is not None and st.state == STATE_ON:
            await self._call(fan.split(".", 1)[0], "turn_off", {"entity_id": fan})
            self._log("LUEFTER", "Lüfter ausgeschaltet (Luke zu)")

    async def _heating_restore(self) -> None:
        climate = self.cfg.get(CONF_CLIMATE)
        if not self.heating_lowered or not climate:
            self.heating_lowered = False
            return
        st = self._state(climate)
        if st is None or st.state in BAD_STATES:
            if not self._heating_warned:
                self._log("FEHLER", "Thermostat nicht erreichbar – Heizung wird zurückgestellt, sobald es wieder da ist")
                self._heating_warned = True
            return  # heating_lowered bleibt gesetzt, Sicherheitsnetz versucht es erneut
        self._heating_warned = False
        if self.cfg[CONF_HEATING_RESTORE] == HEATING_RESTORE_PREVIOUS and self.saved_setpoint is not None:
            temp = self.saved_setpoint
        else:
            temp = float(self.cfg[CONF_HEATING_NORMAL_TEMP])
        self.heating_lowered = False
        self.saved_setpoint = None
        await self._call("climate", "set_temperature", {"entity_id": climate, "temperature": temp})
        self._log("HEIZUNG", f"Heizung zurück auf {temp:.1f} °C")

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        context = Context()
        self._own_contexts.append(context.id)  # eigene Befehle nicht als 'von Hand' werten
        try:
            await self.hass.services.async_call(domain, service, data, blocking=False, context=context)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Aufruf %s.%s fehlgeschlagen", domain, service)
            self._log("FEHLER", f"Aufruf {domain}.{service} fehlgeschlagen")

    def _dwd_text(self) -> str:
        level = self._num(self.cfg.get(CONF_DWD))
        return f"DWD-Warnstufe {level:.0f}." if level and level > 0 else ""

    async def _notify(self, title: str, message: str, *, critical: bool = False, alexa: str | None = None) -> None:
        service = (self.cfg.get(CONF_NOTIFY_APP) or "").strip()
        if service and "." in service:
            domain, name = service.split(".", 1)
            await self._call(domain, name, {"title": title, "message": message})
        if self.cfg[CONF_NOTIFY_PERSISTENT]:
            persistent_notification.async_create(self.hass, message, title=title, notification_id=f"{DOMAIN}_{self.entry.entry_id}")
        alexa_entity = self.cfg.get(CONF_ALEXA)
        if alexa and alexa_entity and (self.cfg[CONF_ALEXA_MODE] == "all" or critical):
            volume = self.cfg[CONF_ALEXA_VOLUME]
            await self._call("notify", "send_message",
                             {"entity_id": alexa_entity, "message": f"<prosody volume='{volume}'>{alexa}</prosody>"})

    # ════════════════════════════════════════════════════════════════════
    # Steuerbar über Entitäten
    # ════════════════════════════════════════════════════════════════════

    async def async_set_enabled(self, value: bool) -> None:
        self.enabled = value
        if value:
            self.pause_until = None
            self._cancel("pause")
            if self.mode == MODE_MANUAL and self.vent_end is None and self.is_open():
                self._set_vent_end(dt_util.utcnow() + timedelta(minutes=self._manual_minutes()))
                self._log("HAND_AUF", f"Automatik wieder an – offene Luke schließt in {self._manual_minutes():.0f} min")
        self._log("AKTIV" if value else "DEAKTIV", f"Automatik {'aktiviert' if value else 'deaktiviert'} (Schalter)")
        self._publish()

    async def async_set_pause(self, value: bool) -> None:
        if value:
            self._start_pause()
            self._log("PAUSE", f"Pause für {self.cfg[CONF_PAUSE_DURATION]} min (Schalter)")
        else:
            self.pause_until = None
            self._cancel("pause")
            self._log("PAUSE_ENDE", "Pause beendet (Schalter)")
        self._publish()

    async def async_vent_now(self) -> None:
        """Taste 'Jetzt lüften': öffnet auf die passende Weite, gilt als Handöffnung."""
        if self.alarm_active():
            self._log("ALARM", "‚Jetzt lüften‘ abgelehnt – Alarm aktiv")
            await self._notify("🚨 Dachluke", "Lüften abgelehnt, Alarm ist aktiv.", critical=True)
            return
        if self.is_open():
            if self.mode == MODE_MANUAL:
                self._set_vent_end(dt_util.utcnow() + timedelta(minutes=self._manual_minutes()))
                self._log("HAND_AUF", f"‚Jetzt lüften‘ erneut gedrückt – läuft weitere {self._manual_minutes():.0f} min")
                self._publish()
            return
        target = self.target()
        if target <= 0:  # Wetter gesperrt: nur minimal
            target = int(self.cfg[CONF_POS_RESTRICTED])
        self._button_at["open"] = (dt_util.utcnow(), "per Dashboard-Taste ‚Jetzt lüften‘")
        await self._cover_to(target)

    async def async_stop_venting(self) -> None:
        """Taste 'Lüftung beenden': schließt wie von Hand (mit Pause)."""
        if self.is_open() is False:
            return
        self._button_at["close"] = (dt_util.utcnow(), "per Dashboard-Taste ‚Lüftung beenden‘")
        await self._call("cover", "close_cover", {"entity_id": self.cfg[CONF_COVER]})

    async def async_set_chart_range(self, option: str) -> None:
        self.chart_range = option
        self._publish()

    async def async_reset_counters(self) -> None:
        self.counters = {k: 0 for k in COUNTERS}
        self.counters_since = dt_util.utcnow()
        self._log("RESET", "Analyse-Zähler zurückgesetzt")
        self._publish()

    # ════════════════════════════════════════════════════════════════════
    # Hilfen
    # ════════════════════════════════════════════════════════════════════

    def _buttons(self) -> dict[str, tuple[str, bool]]:
        result: dict[str, tuple[str, bool]] = {}
        for key, role, remote in (
            (CONF_BUTTON_OPEN, "open", False),
            (CONF_BUTTON_CLOSE, "close", False),
            (CONF_REMOTE_OPEN, "open", True),
            (CONF_REMOTE_CLOSE, "close", True),
        ):
            if eid := self.cfg.get(key):
                result[eid] = (role, remote)
        return result

    def _at(self, key: str, when: datetime, action: Callable[[datetime], Any]) -> None:
        self._cancel(key)

        @callback
        def _fire(now: datetime) -> None:
            self._timers.pop(key, None)

            async def _run() -> None:
                try:
                    await action(now)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Fehler im Zeitablauf %s", key)
                self._publish()

            self.hass.async_create_task(_run())

        self._timers[key] = async_track_point_in_utc_time(self.hass, _fire, when)

    def _cancel(self, key: str) -> None:
        if unsub := self._timers.pop(key, None):
            unsub()

    def _log(self, code: str, text: str) -> None:
        now = dt_util.now()
        self.protocol.append({"t": now.isoformat(timespec="seconds"), "code": code, "text": text})
        _LOGGER.debug("%s: %s", code, text)
        if self.hass.services.has_service("logbook", "log"):
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "logbook", "log", {"name": self.entry.title, "message": text, "domain": DOMAIN}, blocking=False
                )
            )

    @property
    def last_event(self) -> str | None:
        if not self.protocol:
            return None
        last = self.protocol[-1]
        stamp = dt_util.parse_datetime(last["t"])
        prefix = stamp.strftime("%d.%m. %H:%M") if stamp else ""
        return f"{prefix};{last['code']};{last['text']}"[:255]

    def snapshot(self) -> dict[str, Any]:
        """Daten für die Seitenleisten-Seite."""
        return {
            "status": self.status,
            "enabled": self.enabled,
            "mode": self.mode,
            "rise": self.rise,
            "baseline": self.baseline,
            "baseline_ah": self.baseline_ah,
            "abs_humidity": self.abs_humidity(),
            "peak": self.peak,
            "shower_end": _ts(self.shower_end),
            "vent_end": _ts(self.vent_end),
            "pause_until": _ts(self.pause_until),
            "blockers": self.open_blockers(),
            "target": self.target(),
            "counters": self.counters,
            "counters_since": _ts(self.counters_since),
            "last_duration": self.last_duration,
            "protocol": list(self.protocol)[-PROTOCOL_LEN:],
            "sources": {
                "humidity": self.cfg[CONF_HUMIDITY_SENSOR],
                "temperature": self.cfg.get(CONF_TEMP_SENSOR),
                "room_humidity": self.cfg.get(CONF_ROOM_HUMIDITY),
                "position": self.pos_entity,
                "cover": self.cfg[CONF_COVER],
                "lights": self.cfg.get(CONF_LIGHTS) or [],
                "fan": self.cfg.get(CONF_FAN),
                "climate": self.cfg.get(CONF_CLIMATE),
                "weather": self.cfg.get(CONF_WEATHER),
            },
            "settings": {
                "rise_threshold": self.cfg[CONF_RISE_THRESHOLD],
                "close_offset": self.cfg[CONF_CLOSE_OFFSET],
                "close_abs": self.cfg[CONF_CLOSE_ABS],
                "max_open": self.cfg[CONF_MAX_OPEN],
                "manual_duration": self.cfg[CONF_MANUAL_DURATION],
                "heating_enabled": self.cfg[CONF_HEATING_ENABLED],
                "heating_vent_temp": self.cfg[CONF_HEATING_VENT_TEMP],
                "heating_ineffective": self.heating_ineffective,
                "stall_enabled": self.cfg[CONF_STALL_ENABLED],
                "stall_minutes": self.cfg[CONF_STALL_MINUTES],
                "require_light": self.cfg[CONF_REQUIRE_LIGHT],
            },
        }

    def _publish(self) -> None:
        self._store.async_delay_save(self._serialize, 5)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))
