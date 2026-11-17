"""Lüfter läuft auch bei geschlossener Luke, solange der Raum zu feucht ist (17.11.)."""

from pytest_homeassistant_custom_component.common import async_mock_service

from tests.test_controller import POS, WEATHER, step
from tests.test_room_sensor import ROOM, _setup

FAN = "fan.bad_lufter"


async def _fan_setup(hass, freezer, **extra):
    hass.states.async_set(FAN, "off")
    on = async_mock_service(hass, "fan", "turn_on")
    off = async_mock_service(hass, "fan", "turn_off")
    entry, calls = await _setup(hass, freezer, fan=FAN, fan_humidity_limit=61, **extra)
    calls["on"], calls["off"] = on, off
    assert not on, "Raum 60 % unter 61 %"
    return entry.runtime_data, calls


async def test_fan_runs_while_room_humid(hass, freezer):
    c, calls = await _fan_setup(hass, freezer)
    await step(hass, freezer, 1, ROOM, "62")
    assert calls["on"] and c.fan_humid
    hass.states.async_set(FAN, "on")
    await step(hass, freezer, 5, ROOM, "60")
    assert not calls["off"], "Hysterese: erst bei 59 % aus"
    await step(hass, freezer, 5, ROOM, "59")
    assert calls["off"] and not c.fan_humid
    assert any(p["code"] == "LUEFTER" and "unter 59 %" in p["text"] for p in c.protocol)


async def test_fan_keeps_running_after_hatch_closes(hass, freezer):
    c, calls = await _fan_setup(hass, freezer)
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 20, "humidity": 80})
    await c.async_vent_now()
    await step(hass, freezer, 0.2, POS, "100")
    assert calls["on"]
    hass.states.async_set(FAN, "on")
    await step(hass, freezer, 0.5, ROOM, "63")
    await step(hass, freezer, 16)              # 15 min Handöffnung, außen feucht → zu
    assert calls["close"]
    await step(hass, freezer, 0.2, POS, "0")
    assert not calls["off"], "Raum 63 % – Lüfter läuft weiter"
    assert any(p["code"] == "LUEFTER" and "läuft weiter" in p["text"] for p in c.protocol)
    assert c.fan_humid


async def test_manual_fan_off_is_respected(hass, freezer):
    c, calls = await _fan_setup(hass, freezer)
    await step(hass, freezer, 1, ROOM, "62")
    assert len(calls["on"]) == 1
    hass.states.async_set(FAN, "on")
    await step(hass, freezer, 1)
    hass.states.async_set(FAN, "off")           # jemand schaltet ihn aus
    await step(hass, freezer, 1, ROOM, "63")
    assert len(calls["on"]) == 1, "30 min Ruhe"
    await step(hass, freezer, 31, ROOM, "64")
    assert len(calls["on"]) == 2


async def test_fan_humid_off_by_default(hass, freezer):
    hass.states.async_set(FAN, "off")
    entry, calls = await _setup(hass, freezer, fan=FAN)
    on = async_mock_service(hass, "fan", "turn_on")
    await step(hass, freezer, 1, ROOM, "70")
    assert not on


async def test_automatic_off_stops_humid_fan(hass, freezer):
    c, calls = await _fan_setup(hass, freezer)
    await step(hass, freezer, 1, ROOM, "62")
    hass.states.async_set(FAN, "on")
    await c.async_set_enabled(False)
    await hass.async_block_till_done()
    assert calls["off"]
