"""Steuerlogik und Analyse der Dachluke."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.components import persistent_notification
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import logic
from .const import (
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
)

_LOGGER = logging.getLogger(__name__)

MODE_IDLE = "idle"
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
MODE_SECOND = "second"

PENDING_SECONDS = 120
FAILURE_DELAY = timedelta(minutes=5)
SHOWER_CHECK = timedelta(minutes=10)
PROTOCOL_LEN = 100
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
        self.vent_end: datetime | None = None
        self.baseline: float | None = None
        self.pause_until: datetime | None = None
        self.second_at: datetime | None = None
        self.saved_setpoint: float | None = None
        self.heating_lowered = False
        self.blocked_override = False
        self.last_duration: float | None = None
        self.last_open: datetime | None = None
        self.counters: dict[str, int] = {k: 0 for k in COUNTERS}
        self.counters_since: datetime = dt_util.utcnow()
        self.protocol: deque[dict[str, str]] = deque(maxlen=PROTOCOL_LEN)

        # Flüchtiger Zustand
        self.samples: deque[logic.Sample] = deque()
        self.rise: float | None = None
        self.shower: dict[str, Any] | None = None
        self._pending: tuple[str, datetime] | None = None
        self._button_seen: dict[str, str] = {}

    # ════════════════════════════════════════════════════════════════════
    # Lebenszyklus
    # ════════════════════════════════════════════════════════════════════

    async def async_start(self) -> None:
        await self._restore()
        watched = [
            e
            for e in (
                self.cfg[CONF_HUMIDITY_SENSOR],
                self.cfg[CONF_POSITION_SENSOR],
                self.cfg.get(CONF_WEATHER),
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
        hum = self._num(self.cfg[CONF_HUMIDITY_SENSOR])
        if hum is not None:
            self.samples.append((dt_util.utcnow(), hum))
        self.hass.async_create_task(self._resume_after_start())

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for key in list(self._timers):
            self._cancel(key)
        await self._store.async_save(self._serialize())

    async def _restore(self) -> None:
        data = await self._store.async_load() or {}
        self.enabled = data.get("enabled", True)
        self.mode = data.get("mode", MODE_IDLE)
        self.opened_at = _dt(data.get("opened_at"))
        self.vent_end = _dt(data.get("vent_end"))
        self.baseline = data.get("baseline")
        self.pause_until = _dt(data.get("pause_until"))
        self.second_at = _dt(data.get("second_at"))
        self.saved_setpoint = data.get("saved_setpoint")
        self.heating_lowered = data.get("heating_lowered", False)
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
            "vent_end": _ts(self.vent_end),
            "baseline": self.baseline,
            "pause_until": _ts(self.pause_until),
            "second_at": _ts(self.second_at),
            "saved_setpoint": self.saved_setpoint,
            "heating_lowered": self.heating_lowered,
            "blocked_override": self.blocked_override,
            "last_duration": self.last_duration,
            "last_open": _ts(self.last_open),
            "counters": self.counters,
            "counters_since": _ts(self.counters_since),
            "protocol": list(self.protocol),
        }

    async def _resume_after_start(self) -> None:
        """Nach (Neu-)Start Timer wiederherstellen und Widersprüche auflösen."""
        now = dt_util.utcnow()
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
        elif open_:
            # Offen, aber keine bekannte Lüftung: wie manuelles Öffnen behandeln
            self.mode = MODE_MANUAL
            self.opened_at = now
            self.vent_end = now + timedelta(minutes=self._manual_minutes())
            self._at("vent", self.vent_end, self._vent_elapsed)
            self._log("NEUSTART", "Luke beim Start offen vorgefunden – Timer gestartet")
        elif self.heating_lowered:
            await self._heating_restore()
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

    def position(self) -> float | None:
        pos = self._num(self.cfg[CONF_POSITION_SENSOR])
        if pos is None:
            cover = self._state(self.cfg[CONF_COVER])
            if cover and cover.state not in BAD_STATES:
                cp = cover.attributes.get("current_position")
                if cp is not None:
                    return float(cp)
        return pos

    def is_open(self) -> bool | None:
        pos = self.position()
        return None if pos is None else pos > 0

    def humidity(self) -> float | None:
        return self._num(self.cfg[CONF_HUMIDITY_SENSOR])

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

    def weather_restricted(self) -> bool:
        return self.weather_state() in (self.cfg[CONF_RESTRICTED] or [])

    def _weather_attr(self, key: str) -> float | None:
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
        if self.weather_blocked():
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
            if eid == cfg[CONF_POSITION_SENSOR]:
                await self._on_position(old, new)
            if eid in self._buttons():
                await self._on_button(eid, new)
            if eid in (cfg.get(CONF_LIGHTS) or []) and new and new.state == STATE_ON:
                await self._evaluate_open("licht")
            if eid == cfg.get(CONF_WEATHER):
                await self._on_weather(old, new)
            if eid == cfg.get(CONF_ALARM):
                await self._on_alarm()
            if eid == cfg.get(CONF_CONTACT):
                self._schedule_contact_check()
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
        self.rise = logic.humidity_rise(self.samples, now)
        rise = self.rise or 0.0

        # Dusche erkennen (für die Analyse, unabhängig von der Steuerung)
        if self.shower is None and rise >= float(self.cfg[CONF_SHOWER_DETECT]):
            self.shower = {"start": now, "max_rise": rise, "light": self.lights_on(), "blockers": set()}
            self.counters["showers"] += 1
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
            self.baseline = logic.baseline_humidity(self.samples, now) if self.baseline is None else self.baseline
            self._set_vent_end(now + timedelta(minutes=self._max_minutes()))
            self._log("UEBERNAHME", f"Dusche während Handöffnung erkannt (+{rise:.1f} %/5 min) – Automatik übernimmt")
        elif self.mode == MODE_AUTO and rise >= threshold and self.opened_at:
            cap = self.opened_at + timedelta(minutes=2 * self._max_minutes())
            new_end = min(now + timedelta(minutes=self._max_minutes()), cap)
            if self.vent_end is None or new_end > self.vent_end:
                self._set_vent_end(new_end)

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
        self._schedule_contact_check()
        was_open = old_pos is not None and old_pos > 0
        if new_pos > 0 and not was_open:
            await self._on_opened(new_pos)
        elif new_pos == 0 and (was_open or self.mode != MODE_IDLE):
            await self._on_closed()

    @staticmethod
    def _parse_pos(state: State | None) -> float | None:
        if state is None or state.state in BAD_STATES:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _take_pending(self, kind: str) -> bool:
        pending = self._pending
        if pending and pending[0] == kind and dt_util.utcnow() <= pending[1]:
            self._pending = None
            return True
        return False

    async def _on_opened(self, pos: float) -> None:
        if self._take_pending("open"):
            return
        if self.mode != MODE_IDLE:
            return
        now = dt_util.utcnow()
        if self.alarm_active():
            self._log("ALARM", "Öffnung bei aktivem Alarm – Luke wird wieder geschlossen")
            await self._notify("🚨 Dachluke", "Öffnung bei Alarm verhindert.", critical=True,
                               alexa="Achtung. Dachluke bei Alarm geöffnet. Sie wird geschlossen.")
            await self._close("sicherheit", "Alarm aktiv", from_manual=True)
            return
        self.mode = MODE_MANUAL
        self.opened_at = now
        self.last_open = now
        self.pause_until = None
        self._cancel("pause")
        self.baseline = logic.baseline_humidity(self.samples, now)
        self.counters["open_manual"] += 1
        self._set_vent_end(now + timedelta(minutes=self._manual_minutes()))
        await self._heating_lower()
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
            self._log("HAND_AUF", f"Von Hand geöffnet auf {pos:.0f} % – schließt nach {self._manual_minutes():.0f} min")
            await self._notify("🪟 Dachluke geöffnet", f"Von Hand geöffnet. Schließt nach {self._manual_minutes():.0f} min.",
                               alexa="Dachluke von Hand geöffnet.")
        if (self.rise or 0) >= float(self.cfg[CONF_RISE_THRESHOLD]):
            self.mode = MODE_AUTO
            self._set_vent_end(now + timedelta(minutes=self._max_minutes()))
            self._log("UEBERNAHME", "Steigung über Schwelle – Automatik übernimmt die Handöffnung")

    async def _on_closed(self) -> None:
        if self._take_pending("close"):
            return
        if self.mode == MODE_IDLE and not self.heating_lowered:
            return
        self.counters["close_manual"] += 1
        await self._finish_vent("hand")
        self._start_pause()
        self._log("HAND_ZU", f"Von Hand geschlossen – Pause {self.cfg[CONF_PAUSE_DURATION]} min")
        await self._notify("⏸️ Dachluke", f"Von Hand geschlossen, Automatik pausiert für {self.cfg[CONF_PAUSE_DURATION]} min.",
                           alexa="Dachluke geschlossen. Automatik pausiert.")

    async def _on_button(self, eid: str, new: State | None) -> None:
        if new is None or new.state in BAD_STATES:
            return
        if self._button_seen.get(eid) == new.state:
            return  # wiederhergestellter Zustand, kein neuer Tastendruck
        self._button_seen[eid] = new.state
        etype = new.attributes.get("event_type")
        role, remote = self._buttons()[eid]
        short, long_ = etype in EVENT_SHORT, etype in EVENT_LONG
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
        if self.mode in (MODE_AUTO, MODE_SECOND):
            target = self.target()
            pos = self.position() or 0
            if target > 0 and abs(pos - target) >= float(self.cfg[CONF_POS_TOLERANCE]):
                await self._command_position(target)
                old_s = old.state if old else "?"
                self._log("WETTER", f"{old_s} → {new.state}: Position {pos:.0f} % → {target} %")
                await self._notify("🪟 Dachluke angepasst", f"Wetter {old_s} → {new.state}. Position {pos:.0f} % → {target} %.",
                                   critical=True, alexa=f"Neues Wetter. Dachluke auf {target} Prozent angepasst.")

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
        self.baseline = logic.baseline_humidity(self.samples, now)
        self.counters["open_auto"] += 1
        self._set_vent_end(now + timedelta(minutes=self._max_minutes()))
        self._at("min_open", now + timedelta(minutes=float(self.cfg[CONF_MIN_OPEN])), self._min_open_elapsed)
        self._cancel("second_wait")
        self.second_at = None
        await self._command_position(target)
        await self._heating_lower()
        hum = self.humidity()
        frost = " ❄️ Frost" if self.frost_active() else ""
        self._log(
            "AUTO_AUF",
            f"Automatisch geöffnet auf {target} % (Auslöser {trigger}, +{self.rise:.1f} %/5 min, rF {hum:.0f} %, Basis {self.baseline or 0:.0f} %){frost}",
        )
        await self._notify("🪟 Dachluke geöffnet", f"{target} %, Steigung +{self.rise:.1f} %/5 min, rF {hum:.0f} %.{frost}",
                           alexa="Dachluke geöffnet. Lüftung aktiv.")

    async def _evaluate_close(self) -> None:
        if self.mode != MODE_AUTO or not self.opened_at:
            return
        if dt_util.utcnow() - self.opened_at < timedelta(minutes=float(self.cfg[CONF_MIN_OPEN])):
            return
        indoor_dew = self._num(self.cfg.get(CONF_INDOOR_DEW))
        reason = logic.close_reason(
            humidity=self.humidity(),
            baseline=self.baseline,
            close_offset=float(self.cfg[CONF_CLOSE_OFFSET]),
            close_abs=float(self.cfg[CONF_CLOSE_ABS]),
            indoor_dew=indoor_dew,
            outdoor_dew=self._weather_attr("dew_point"),
            dew_offset=float(self.cfg[CONF_DEW_OFFSET]),
            dew_enabled=bool(self.cfg[CONF_DEW_ENABLED]),
        )
        if reason:
            text = {
                "basis": f"Feuchte {self.humidity():.0f} % wieder nahe Ausgangswert {self.baseline or 0:.0f} %",
                "schwelle": f"Feuchte {self.humidity():.0f} % unter {float(self.cfg[CONF_CLOSE_ABS]):.0f} %",
                "taupunkt": f"Taupunkt innen {indoor_dew} °C unter außen + Offset",
            }[reason]
            await self._close("feuchte", text)

    async def _close(self, kind: str, text: str, *, from_manual: bool = False) -> None:
        """Luke schließen. kind: feuchte | timer | nachlueften | sicherheit | hand."""
        was_mode = self.mode
        self._pending = ("close", dt_util.utcnow() + timedelta(seconds=PENDING_SECONDS))
        await self._call("cover", "close_cover", {"entity_id": self.cfg[CONF_COVER]})
        counter = {
            "feuchte": "close_humidity",
            "timer": "close_timer",
            "sicherheit": "close_safety",
            "hand": "close_manual",
        }.get(kind)
        if counter and (was_mode != MODE_IDLE or kind == "sicherheit"):
            self.counters[counter] += 1
        await self._finish_vent(kind)
        if kind != "hand":
            self._log("ZU", f"Geschlossen: {text}")
        if kind in ("feuchte", "timer") and not from_manual:
            await self._notify("✅ Dachluke geschlossen", text,
                               critical=kind == "timer",
                               alexa="Lüftung abgeschlossen. Dachluke geschlossen.")
        if kind in ("feuchte", "timer") and was_mode == MODE_AUTO:
            self._schedule_second_vent()

    async def _finish_vent(self, kind: str) -> None:
        now = dt_util.utcnow()
        if self.opened_at:
            self.last_duration = round((now - self.opened_at).total_seconds() / 60, 1)
        self.mode = MODE_IDLE
        self.opened_at = None
        self.vent_end = None
        self.blocked_override = False
        for key in ("vent", "min_open"):
            self._cancel(key)
        await self._heating_restore()

    # ════════════════════════════════════════════════════════════════════
    # Zeitgesteuerte Abläufe
    # ════════════════════════════════════════════════════════════════════

    def _set_vent_end(self, when: datetime) -> None:
        self.vent_end = when
        self._at("vent", when, self._vent_elapsed)

    async def _vent_elapsed(self, _now: datetime) -> None:
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
        hum = self.humidity()
        if (
            hum is not None
            and hum > float(self.cfg[CONF_SECOND_THRESHOLD])
            and self.mode == MODE_IDLE
            and self.is_open() is False
            and self.enabled
            and not self.paused()
            and not self.alarm_active()
            and not self.weather_blocked()
        ):
            target = self.target()
            now = dt_util.utcnow()
            self.mode = MODE_SECOND
            self.opened_at = now
            self._set_vent_end(now + timedelta(minutes=float(self.cfg[CONF_SECOND_DURATION])))
            await self._command_position(target)
            if self.cfg[CONF_SECOND_HEATING]:
                await self._heating_lower()
            self._log("NACHLUEFTEN", f"Zweites Nachlüften bei {hum:.0f} % für {self.cfg[CONF_SECOND_DURATION]} min")
            await self._notify("🔄 Dachluke", f"Zweites Nachlüften, Restfeuchte {hum:.0f} %.",
                               alexa=f"Zweites Nachlüften. Restfeuchte {hum:.0f} Prozent.")
        else:
            self._log("NACHLUEFTEN", f"Zweites Nachlüften nicht nötig oder gesperrt (rF {hum if hum is not None else '?'} %)")

    async def _shower_check(self, _now: datetime) -> None:
        shower, self.shower = self.shower, None
        if not shower:
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
        await self._notify("⚠️ Dachluke", "Feuchtesensor nicht verfügbar.", critical=True)

    async def _sensor_failed_position(self, _now: datetime) -> None:
        self.counters["sensor_failures"] += 1
        self._log("AUSFALL", "Positionssensor seit 5 min nicht verfügbar – Automatik öffnet nicht")
        await self._notify("⚠️ Dachluke", "Positionssensor nicht verfügbar. Automatisches Öffnen gesperrt.", critical=True,
                           alexa="Achtung. Dachluke Positionssensor ausgefallen.")

    def _schedule_contact_check(self) -> None:
        if not self.cfg.get(CONF_CONTACT):
            return
        when = dt_util.utcnow() + timedelta(seconds=float(self.cfg[CONF_CONTACT_GRACE]))
        self._at("contact", when, self._contact_check)

    async def _contact_check(self, _now: datetime) -> None:
        contact = self._state(self.cfg.get(CONF_CONTACT))
        pos = self.position()
        if contact is None or contact.state in BAD_STATES or pos is None:
            return
        if (pos > 0) != (contact.state == STATE_ON):
            self._log("WIDERSPRUCH", f"Position {pos:.0f} % aber Kontakt {contact.state}")
            await self._notify("⚠️ Dachluke Sensor-Widerspruch",
                               f"Positionssensor {pos:.0f} %, Fensterkontakt {contact.state}. Bitte prüfen.",
                               critical=True, alexa="Achtung. Dachluke Sensorfehler.")

    # ════════════════════════════════════════════════════════════════════
    # Aktionen
    # ════════════════════════════════════════════════════════════════════

    async def _command_position(self, position: int) -> None:
        self._pending = ("open", dt_util.utcnow() + timedelta(seconds=PENDING_SECONDS))
        await self._call("cover", "set_cover_position", {"entity_id": self.cfg[CONF_COVER], "position": int(position)})

    async def _command_manual_open(self) -> None:
        """Öffnen per Fernbedienung ohne Direktverknüpfung."""
        await self._call("cover", "set_cover_position", {"entity_id": self.cfg[CONF_COVER], "position": self.target() or int(self.cfg[CONF_POS_RESTRICTED])})

    async def _heating_lower(self) -> None:
        climate = self.cfg.get(CONF_CLIMATE)
        if not (self.cfg[CONF_HEATING_ENABLED] and climate) or self.heating_lowered:
            return
        st = self._state(climate)
        if st is None or st.state in BAD_STATES:
            return
        current = st.attributes.get("temperature")
        self.saved_setpoint = float(current) if current is not None else None
        self.heating_lowered = True
        await self._call("climate", "set_temperature", {"entity_id": climate, "temperature": float(self.cfg[CONF_HEATING_VENT_TEMP])})

    async def _heating_restore(self) -> None:
        climate = self.cfg.get(CONF_CLIMATE)
        if not self.heating_lowered or not climate:
            self.heating_lowered = False
            return
        if self.cfg[CONF_HEATING_RESTORE] == HEATING_RESTORE_PREVIOUS and self.saved_setpoint is not None:
            temp = self.saved_setpoint
        else:
            temp = float(self.cfg[CONF_HEATING_NORMAL_TEMP])
        self.heating_lowered = False
        self.saved_setpoint = None
        await self._call("climate", "set_temperature", {"entity_id": climate, "temperature": temp})
        self._log("HEIZUNG", f"Heizung zurück auf {temp:.1f} °C")

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=False)
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
                "position": self.cfg[CONF_POSITION_SENSOR],
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
                "require_light": self.cfg[CONF_REQUIRE_LIGHT],
            },
        }

    def _publish(self) -> None:
        self._store.async_delay_save(self._serialize, 5)
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))
