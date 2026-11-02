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
    await step(hass, freezer, 2, HUM, "95")       # Duschsensor löst aus
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
    await step(hass, freezer, 3, ROOM, "63")     # 11,6 g/m³ ≤ 12,0 → Raum wieder nahe Basis
    assert calls["close"]
    bilanz = [p["text"] for p in c.protocol if p["code"] == "BILANZ"][0]
    assert "Dusche: Basis 65 %" in bilanz and "Raum: Basis 60 %, Höchstwert 72 %" in bilanz


async def test_room_humidity_from_climate_attribute(hass, freezer):
    entry, calls = await _setup(hass, freezer, room=CLIMATE)
    c = entry.runtime_data
    assert c.room_humidity() == 60
    await step(hass, freezer, 3, HUM, "75")
    await step(hass, freezer, 2, HUM, "95")
    assert c.baseline == 60
    hass.states.async_set(CLIMATE, "auto", {"current_temperature": 21.5, "current_humidity": 70, "temperature": 21})
    await step(hass, freezer, 3)
    assert c.room_peak == 70
