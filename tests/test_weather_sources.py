"""Außenwerte von Bright Sky (DWD) und Regensensor."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke import logic
from custom_components.dachluke.const import BRIGHTSKY_URL, DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, step  # noqa: F401

RAIN = "sensor.dwdhome_precipitation_now"


def _bs(precip=0.0):
    # Struktur wie brightsky (query.current_weather): weather-Objekt + sources-Liste
    return {
        "weather": {"source_id": 7, "timestamp": "2026-11-02T20:30:00+00:00", "temperature": 7.5,
                    "relative_humidity": 93, "dew_point": 6.4, "precipitation_10": precip, "condition": "dry"},
        "sources": [{"id": 7, "station_name": "Musterstadt", "distance": 8123.0}],
    }


async def _setup(hass, freezer, aioclient_mock, payload=None, status=200, **extra):
    freezer.move_to("2026-11-02 20:00:00+00:00")
    aioclient_mock.get(BRIGHTSKY_URL, json=payload if payload is not None else _bs(), status=status)
    hass.states.async_set(HUM, "62", {"device_class": "humidity"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(WEATHER, "rainy", {"temperature": 9, "humidity": 80, "dew_point": 5})
    calls = {"pos": async_mock_service(hass, "cover", "set_cover_position"),
             "close": async_mock_service(hass, "cover", "close_cover")}
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
                            options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                                     "weather": WEATHER, "brightsky": True, **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def test_brightsky_values_used(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock)
    c = entry.runtime_data
    assert c.outdoor_abs_humidity() == logic.absolute_humidity(7.5, 93)
    assert "DWD Musterstadt, 8 km" in c.context()
    assert c.restricted_now() is False, "Station misst keinen Regen – 'rainy' von Met.no zählt nicht"
    assert c.target() == 80
    assert any(p["code"] == "WETTERQUELLE" and "Musterstadt" in p["text"] for p in c.protocol)


async def test_brightsky_rain_restricts(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_bs(0.3))
    c = entry.runtime_data
    assert c.restricted_now() is True and c.target() == 20
    assert "Regen 0.3 mm" in c.position_reason()


async def test_brightsky_failure_falls_back(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, status=500)
    c = entry.runtime_data
    assert c.outdoor_abs_humidity() == logic.absolute_humidity(9, 80)
    assert c.restricted_now() is None and c.target() == 20  # Wetterzustand 'rainy'
    assert sum(p["code"] == "WETTERQUELLE" for p in c.protocol) == 1


async def test_rain_sensor_has_priority(hass, freezer, aioclient_mock):
    hass.states.async_set(RAIN, "0.0")
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_bs(0.5), rain_sensor=RAIN)
    c = entry.runtime_data
    assert c.target() == 80
    # Luke offen (automatisch), dann setzt Regen ein → Weite wird angepasst
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 1, RAIN, "0.4")
    assert calls["pos"][-1].data["position"] == 20
    assert any(p["code"] == "WETTER" and "Regen" in p["text"] for p in c.protocol)
