"""Taste „Jetzt lüften“ lüftet bis der Raum trocken ist (Auswertung 16.11.)."""

from tests.test_controller import POS, WEATHER, counter, step
from tests.test_room_sensor import ROOM, _setup

DRY = {"temperature": 7, "humidity": 85}     # etwa 6,6 g/m³
HUMID = {"temperature": 20, "humidity": 80}  # etwa 13,8 g/m³


async def _press(hass, freezer, weather=DRY, room="63", **extra):
    entry, calls = await _setup(hass, freezer, room_max_humidity=57, **extra)
    hass.states.async_set(WEATHER, "cloudy", weather)
    hass.states.async_set(ROOM, room, {"device_class": "humidity"})
    c = entry.runtime_data
    await c.async_vent_now()
    await step(hass, freezer, 0.2, POS, "100")
    return c, calls


async def test_vent_now_until_dry(hass, freezer):
    c, calls = await _press(hass, freezer)
    assert any(p["code"] == "HAND_AUF" and "bis Raum unter 57 %" in p["text"] for p in c.protocol)
    await step(hass, freezer, 15)
    assert not calls["close"], "Raum 63 % über 57 %, außen trocken: weiterlüften"
    assert any(p["code"] == "VERLAENGERT" and "Jetzt lüften" in p["text"] for p in c.protocol)
    await step(hass, freezer, 2, ROOM, "56")
    await step(hass, freezer, 4)
    assert calls["close"] and counter(hass, "close_timer") == 1
    assert c.until_dry is False


async def test_vent_now_stops_at_hard_cap(hass, freezer):
    c, calls = await _press(hass, freezer, hard_cap=40)
    for _ in range(5):
        await step(hass, freezer, 5)
    assert not calls["close"]
    await step(hass, freezer, 16)
    assert calls["close"], "Obergrenze 40 min"


async def test_vent_now_humid_outside_closes_after_manual_duration(hass, freezer):
    c, calls = await _press(hass, freezer, weather=HUMID)
    await step(hass, freezer, 15.5)
    assert calls["close"]
    assert not any(p["code"] == "VERLAENGERT" for p in c.protocol)


async def test_vent_now_cold_room_closes(hass, freezer):
    c, calls = await _press(hass, freezer)
    hass.states.async_set("climate.bad_wandthermostat", "auto",
                          {"current_temperature": 17.0, "current_humidity": 63, "temperature": 21})
    await step(hass, freezer, 15.5)
    assert calls["close"]


async def test_device_opening_keeps_fixed_duration(hass, freezer):
    entry, calls = await _setup(hass, freezer, room_max_humidity=57)
    hass.states.async_set(WEATHER, "cloudy", DRY)
    hass.states.async_set(ROOM, "63", {"device_class": "humidity"})
    c = entry.runtime_data
    await step(hass, freezer, 0.2, POS, "100")   # Taste am Gerät
    assert c.until_dry is False
    await step(hass, freezer, 15.5)
    assert calls["close"]


async def test_until_dry_survives_restart(hass, freezer):
    c, calls = await _press(hass, freezer)
    [entry] = hass.config_entries.async_entries("dachluke")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.until_dry is True
