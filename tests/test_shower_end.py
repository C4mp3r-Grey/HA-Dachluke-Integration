"""Duschende-Erkennung und Schließen nach absoluter Feuchte."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service
import pytest

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from custom_components.dachluke import logic
from tests.test_controller import COVER, HUM, POS, WEATHER, counter, st, step  # noqa: F401

TEMP = "sensor.bad_temperatur"


async def _setup(hass, freezer, **extra):
    freezer.move_to("2026-11-01 06:00:00+00:00")
    hass.states.async_set(HUM, "60", {"device_class": "humidity"})
    hass.states.async_set(TEMP, "21", {"device_class": "temperature"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    calls = {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "close": async_mock_service(hass, "cover", "close_cover"),
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
        options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                 "weather": WEATHER, "max_open": 20, "hard_cap": 90, **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def _shower_start(hass, freezer):
    await step(hass, freezer, 3, HUM, "68")
    await step(hass, freezer, 2, HUM, "80")
    await step(hass, freezer, 0.2, POS, "80")


async def test_long_shower_keeps_window_open(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await _shower_start(hass, freezer)
    # 30 Minuten Plateau bei 90-92 %: es wird noch geduscht
    for i in range(10):
        await step(hass, freezer, 3, HUM, "91" if i % 2 else "92")
    assert not calls["close"], "während des Duschens nicht schließen"
    # Duschende: Feuchte fällt um mehr als 3 % vom Höchstwert
    await step(hass, freezer, 3, HUM, "88")
    assert entry.runtime_data.shower_end is not None
    await step(hass, freezer, 3, HUM, "87")
    await step(hass, freezer, 15)
    assert not calls["close"]
    await step(hass, freezer, 3)
    assert calls["close"], "20 min nach Duschende geschlossen"
    assert counter(hass, "close_timer") == 1


async def test_hard_cap_without_shower_end(hass, freezer):
    entry, calls = await _setup(hass, freezer, hard_cap=90)
    await _shower_start(hass, freezer)
    for _ in range(40):
        await step(hass, freezer, 3, HUM, "92")
        if calls["close"]:
            break
    assert calls["close"]
    elapsed = (entry.runtime_data.last_duration or 0)
    assert 88 <= elapsed <= 94


async def test_close_on_absolute_humidity_not_on_heating(hass, freezer):
    entry, calls = await _setup(hass, freezer, temperature_sensor=TEMP)
    c = entry.runtime_data
    await _shower_start(hass, freezer)
    assert c.baseline_ah == pytest.approx(logic.absolute_humidity(21, 60), abs=0.05)
    await step(hass, freezer, 3, HUM, "88")
    await step(hass, freezer, 3, HUM, "80")
    # Heizung wärmt auf 25 °C: rF fällt unter Ausgangswert+3, absolute Feuchte bleibt hoch
    hass.states.async_set(TEMP, "25")
    await step(hass, freezer, 3, HUM, "62")
    assert logic.absolute_humidity(25, 62) > logic.absolute_humidity(21, 60) + 1
    assert not calls["close"], "relative Feuchte allein darf nicht schließen"
    # wirklich getrocknet
    await step(hass, freezer, 3, HUM, "50")
    assert calls["close"]
    assert counter(hass, "close_humidity") == 1
    assert any(p["code"] == "ZU" and "Absolute Feuchte" in p["text"] for p in c.protocol)


async def test_new_shower_after_end_extends_again(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    await _shower_start(hass, freezer)
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "85")
    assert c.shower_end is not None
    # zweite Person duscht
    await step(hass, freezer, 3, HUM, "86")
    await step(hass, freezer, 3, HUM, "94")
    assert c.shower_end is None
    await step(hass, freezer, 18, HUM, "93")
    assert not calls["close"]
