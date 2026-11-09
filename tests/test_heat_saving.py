"""Betriebsart „Wärme sparen“: Lüfter beim Duschen, Luke erst nach dem Duschende, kurz und weit."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, counter, step

FAN = "fan.bad_lufter"
TEMP = "sensor.bad_temperatur"


async def _setup(hass, freezer, **extra):
    freezer.move_to("2026-11-09 05:30:00+00:00")
    hass.states.async_set(HUM, "60", {"device_class": "humidity"})
    hass.states.async_set(TEMP, "20", {"device_class": "temperature"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(FAN, "off")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 4})
    calls = {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "close": async_mock_service(hass, "cover", "close_cover"),
        "on": async_mock_service(hass, "fan", "turn_on"),
        "off": async_mock_service(hass, "fan", "turn_off"),
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
        options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM, "weather": WEATHER,
                 "fan": FAN, "temperature_sensor": TEMP, "max_open": 20, "hard_cap": 60, **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    c = entry.runtime_data
    await c.async_set_operating_mode("heat_saving")
    return entry, calls


async def _shower(hass, freezer):
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")
    hass.states.async_set(FAN, "on")
    for v in ("92", "96", "98"):
        await step(hass, freezer, 2, HUM, v)


async def test_fan_during_shower_hatch_after(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    await _shower(hass, freezer)
    assert calls["on"], "Lüfter läuft beim Duschen"
    assert not calls["pos"], "Luke bleibt während des Duschens zu"
    assert c._save is not None
    await step(hass, freezer, 2, HUM, "93")  # Duschende
    assert calls["pos"] and calls["pos"][-1].data["position"] == 100
    await step(hass, freezer, 0.2, POS, "100")
    assert c.mode == "auto"
    assert any(p["code"] == "AUTO_AUF" and "Wärme sparen, Duschende" in p["text"] for p in c.protocol)
    assert c.last_shower_minutes is not None and c.last_shower_minutes >= 8
    # feste 10 min, keine Verlängerung, kein zweites Nachlüften
    await step(hass, freezer, 5, HUM, "88")
    await step(hass, freezer, 6, HUM, "84")
    assert calls["close"] and counter(hass, "close_timer") == 1
    assert not any(p["code"] == "VERLAENGERT" for p in c.protocol)
    assert c.second_at is None


async def test_closes_after_one_kelvin_cooling(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await _shower(hass, freezer)
    await step(hass, freezer, 2, HUM, "93")
    await step(hass, freezer, 0.2, POS, "100")
    await step(hass, freezer, 3, TEMP, "19.4")
    assert not calls["close"]
    await step(hass, freezer, 3, TEMP, "18.9")
    assert calls["close"] and counter(hass, "close_cold") == 1


async def test_back_to_normal_while_waiting(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    await _shower(hass, freezer)
    await c.async_set_operating_mode("normal")
    await hass.async_block_till_done()
    assert c._save is None and calls["off"]
    assert any(p["code"] == "BETRIEBSART" and "Normal" in p["text"] for p in c.protocol)


async def test_manual_opening_ten_minutes(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await step(hass, freezer, 0.2, POS, "50")
    await step(hass, freezer, 9)
    assert not calls["close"]
    await step(hass, freezer, 2)
    assert calls["close"]


async def test_mode_survives_restart(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.operating_mode == "heat_saving"
    assert hass.states.get("select.dachluke_betriebsart") is not None or any(
        s.entity_id.startswith("select.") and s.state == "heat_saving" for s in hass.states.async_all("select")
    )
