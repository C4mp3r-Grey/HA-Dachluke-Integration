"""Erhöhte Ausgangsfeuchte darf die Lüftung nicht immer weiter verkürzen."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke import logic
from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, step  # noqa: F401

ROOM = "sensor.wandthermostat_feuchte"
CLIMATE = "climate.bad"


async def _setup(hass, freezer):
    freezer.move_to("2026-11-02 06:00:00+00:00")
    hass.states.async_set(HUM, "62", {"device_class": "humidity"})
    hass.states.async_set(ROOM, "60", {"device_class": "humidity"})
    hass.states.async_set(CLIMATE, "auto", {"current_temperature": 21.0, "temperature": 21})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8, "humidity": 85})
    calls = {"pos": async_mock_service(hass, "cover", "set_cover_position"),
             "close": async_mock_service(hass, "cover", "close_cover")}
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
                            options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                                     "room_humidity_sensor": ROOM, "climate": CLIMATE, "weather": WEATHER,
                                     "stall_enabled": False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def test_reference_learned_in_quiet_phases(hass, freezer):
    entry, _ = await _setup(hass, freezer)
    c = entry.runtime_data
    for _ in range(12):
        await step(hass, freezer, 15)
    assert len(c.ref_samples) >= 8
    rh, ah = c.reference()
    assert rh == 60 and ah == logic.absolute_humidity(21.0, 60)


async def test_elevated_baseline_uses_reference(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    c = entry.runtime_data
    for _ in range(12):                      # 3 h Ruhe bei 60 % → Referenz
        await step(hass, freezer, 15)
    # Raum ist noch von einer früheren Dusche feucht
    hass.states.async_set(ROOM, "72")
    await step(hass, freezer, 5, HUM, "72")
    await step(hass, freezer, 3, HUM, "80")
    await step(hass, freezer, 2, HUM, "95")  # neue Dusche
    await step(hass, freezer, 0.2, POS, "80")
    assert calls["pos"]
    assert c.baseline == 72
    t_rh, t_ah = c.close_targets()
    assert t_rh == 60 and abs(t_ah - logic.absolute_humidity(21.0, 60)) < 0.01
    await step(hass, freezer, 3, ROOM, "76")
    await step(hass, freezer, 3, HUM, "88")  # Duschende
    await step(hass, freezer, 3, ROOM, "72")
    assert not calls["close"], "früher hätte er bei Ausgangswert 72 % geschlossen"
    await step(hass, freezer, 3, ROOM, "67")
    assert not calls["close"]
    await step(hass, freezer, 3, ROOM, "63")
    await step(hass, freezer, 3, HUM, "70")      # Dusche über üblichen 62 % + 3 (Referenz des Duschsensors)
    assert not calls["close"]
    await step(hass, freezer, 3, HUM, "64")      # Dusche ≤ übliche 62 + 3
    assert calls["close"]
    zu = [p["text"] for p in c.protocol if p["code"] == "ZU"][-1]
    assert "übliche Raumfeuchte statt erhöhter Ausgangsfeuchte" in zu


def test_outdoor_floor():
    rh, ah = logic.close_targets(baseline=60, baseline_ah=9.0, ref_rh=None, ref_ah=None, outdoor_ah=10.0)
    assert ah == 10.5 and rh == 60
