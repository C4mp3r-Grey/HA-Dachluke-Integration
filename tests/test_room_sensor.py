"""Zwei Sensoren: Dusche erkennt, Raum entscheidet über das Schließen."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke import logic
from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, counter, step  # noqa: F401

ROOM = "sensor.wandthermostat_feuchte"
CLIMATE = "climate.bad_wandthermostat"


async def _setup(hass, freezer, room=ROOM, **extra):
    freezer.move_to("2026-11-01 06:00:00+00:00")
    hass.states.async_set(HUM, "65", {"device_class": "humidity"})
    hass.states.async_set(ROOM, "60", {"device_class": "humidity"})
    hass.states.async_set(CLIMATE, "auto", {"current_temperature": 21.0, "current_humidity": 60, "temperature": 21})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    calls = {"pos": async_mock_service(hass, "cover", "set_cover_position"),
             "close": async_mock_service(hass, "cover", "close_cover")}
    entry = MockConfigEntry(
        domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
        options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                 "room_humidity_sensor": room, "climate": CLIMATE, "weather": WEATHER,
                 "stall_enabled": False, **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def test_room_sensor_decides_close(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")       # Duschsensor löst aus
    assert calls["pos"]
    assert c.baseline == 60 and c.shower_baseline == 65
    assert c.baseline_ah == logic.absolute_humidity(21.0, 60)
    await step(hass, freezer, 0.2, ROOM, "72")
    await step(hass, freezer, 3, HUM, "100")
    await step(hass, freezer, 3, HUM, "90")      # Duschende am Duschsensor
    assert c.shower_end is not None
    await step(hass, freezer, 3, HUM, "70")      # Duschsensor schon nahe Basis …
    assert not calls["close"], "… aber der Raum ist noch feucht (72 %)"
    await step(hass, freezer, 3, ROOM, "67")     # 12,3 g/m³ > Basis 11,0 + 1
    assert not calls["close"]
    await step(hass, freezer, 3, ROOM, "63")     # 11,6 g/m³ ≤ 12,0 → Raum wieder nahe Basis …
    assert not calls["close"], "… aber über der Dusche ist es mit 70 % noch feucht"
    await step(hass, freezer, 3, HUM, "67")      # Dusche ≤ Basis 65 + 3
    assert calls["close"]
    zu = [p["text"] for p in c.protocol if p["code"] == "ZU"][-1]
    assert "Dusche 67 %" in zu
    bilanz = [p["text"] for p in c.protocol if p["code"] == "BILANZ"][0]
    assert "Dusche: Basis 65 %" in bilanz and "Raum: Basis 60 %, Höchstwert 72 %" in bilanz


async def test_room_humidity_from_climate_attribute(hass, freezer):
    entry, calls = await _setup(hass, freezer, room=CLIMATE)
    c = entry.runtime_data
    assert c.room_humidity() == 60
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")
    assert c.baseline == 60
    hass.states.async_set(CLIMATE, "auto", {"current_temperature": 21.5, "current_humidity": 70, "temperature": 21})
    await step(hass, freezer, 3)
    assert c.room_peak == 70


async def test_no_close_while_showering_and_duration_set(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")       # öffnet
    for v in ("99", "100", "100", "100"):         # 12 min Duschen, Raum reagiert kaum
        await step(hass, freezer, 3, HUM, v)
        hass.states.async_set(ROOM, "61")
    await hass.async_block_till_done()
    assert not calls["close"], "während des Duschens nicht schließen"
    await step(hass, freezer, 3, HUM, "92")       # Duschende
    assert c.last_shower_minutes is not None and c.last_shower_minutes >= 10
    await step(hass, freezer, 6, ROOM, "61")
    assert not calls["close"], "Raum hat noch gar nicht reagiert, Dusche noch bei 92 %"
    await step(hass, freezer, 3, HUM, "66")
    assert calls["close"]
    from homeassistant.helpers import entity_registry as er
    eid = er.async_get(hass).async_get_entity_id("sensor", "dachluke", f"{entry.entry_id}_last_shower_duration")
    assert float(hass.states.get(eid).state) >= 10


async def test_lagging_room_sensor_scenario_from_log(hass, freezer):
    """Nachgestellt vom 02.11. 17:18: Raumsensor reagiert erst nach ~15 min."""
    entry, calls = await _setup(hass, freezer, stall_enabled=True)
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")       # öffnet
    await step(hass, freezer, 5, HUM, "100")
    await step(hass, freezer, 3, HUM, "96")       # Duschende
    assert not calls["close"]
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "84")
    await step(hass, freezer, 3, ROOM, "70")      # Raum reagiert jetzt erst
    await step(hass, freezer, 3, HUM, "78")
    assert not calls["close"], "Raum flach, aber Dusche fällt → keine Stagnation"
    await step(hass, freezer, 3, HUM, "72")
    await step(hass, freezer, 3, ROOM, "63")
    await step(hass, freezer, 2, HUM, "67")
    assert calls["close"]
    assert counter(hass, "close_humidity") == 1


async def test_timer_extends_while_drying(hass, freezer):
    entry, calls = await _setup(hass, freezer, max_open=10)
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 3, HUM, "90")       # Duschende
    hass.states.async_set(ROOM, "75")
    for v in ("88", "85", "82", "80"):            # 12 min, fällt stetig
        await step(hass, freezer, 3, HUM, v)
    assert not calls["close"], "nach 10 min verlängert, weil die Trocknung läuft"
    assert any(p["code"] == "VERLAENGERT" for p in c.protocol)


async def test_cold_protection_closes(hass, freezer):
    entry, calls = await _setup(hass, freezer, cold_min_temp=18.0)
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 3, HUM, "90")       # Duschende
    hass.states.async_set(CLIMATE, "auto", {"current_temperature": 17.6, "current_humidity": 70, "temperature": 21})
    await step(hass, freezer, 3)
    assert calls["close"]
    assert counter(hass, "close_cold") == 1
    assert any("kühlt aus" in p["text"] for p in entry.runtime_data.protocol)


async def test_prediction_and_wall_humidity_logged(hass, freezer):
    hass.states.async_set("sensor.vent_optimization", "18")
    entry, calls = await _setup(hass, freezer, vent_prediction_sensor="sensor.vent_optimization")
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")
    auf = [p["text"] for p in c.protocol if p["code"] == "AUTO_AUF"][-1]
    assert "Vorhersage Lüftdauer 18 min" in auf and "Wandfeuchte" in auf
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 3, ROOM, "60")
    bilanz = [p["text"] for p in c.protocol if p["code"] == "BILANZ"][-1]
    assert "Vorhersage Lüftdauer 18 min, tatsächlich" in bilanz and "Wandfeuchte" in bilanz


async def _shower_until_room_near_base(hass, freezer, weather_attrs, **extra):
    entry, calls = await _setup(hass, freezer, room_max_humidity=55, **extra)
    hass.states.async_set(WEATHER, "cloudy", weather_attrs)
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 0.2, ROOM, "72")
    await step(hass, freezer, 3, HUM, "100")
    await step(hass, freezer, 3, HUM, "90")      # Duschende
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 3, ROOM, "63")     # nahe Basis, früher hätte das gereicht …
    await step(hass, freezer, 3, HUM, "67")      # … und Dusche wieder unten
    return entry, calls


async def test_room_max_keeps_venting_until_55(hass, freezer):
    """Auswertung 15.11.: Raum soll nach dem Duschen auf höchstens 55 % kommen, wenn die Außenluft trocken ist."""
    entry, calls = await _shower_until_room_near_base(hass, freezer, {"temperature": 7, "humidity": 85})
    c = entry.runtime_data
    too, why = c.room_too_humid()
    assert too, why
    assert not calls["close"], "Raum 63 % > 55 %, Außenluft trocken: weiterlüften"
    await step(hass, freezer, 3, ROOM, "58")
    assert not calls["close"]
    await step(hass, freezer, 3, ROOM, "55")
    assert calls["close"] and counter(hass, "close_humidity") == 1


async def test_room_max_ignored_when_outdoor_humid(hass, freezer):
    """Sommer: Außenluft kaum trockener – normale Regeln, schließt bei 63 %."""
    entry, calls = await _shower_until_room_near_base(hass, freezer, {"temperature": 22, "humidity": 70})
    assert not entry.runtime_data.room_too_humid()[0]
    assert calls["close"]


def test_rise_start_ignores_slow_creep():
    """15.11.: 67,1 → 68,4 % in 15 min Kriechen, dann steil – Beginn ist der letzte langsame Messwert."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 11, 15, 7, 55, tzinfo=timezone.utc)
    m = lambda minutes: t0 + timedelta(minutes=minutes)  # noqa: E731
    samples = [(m(0), 67.1), (m(1.7), 67.4), (m(6.7), 67.8), (m(11.7), 68.2), (m(16.7), 68.4),
               (m(18.1), 69.8), (m(18.6), 78.3), (m(19.1), 82.8)]
    assert logic.rise_start(samples, 67.1) == m(16.7)
