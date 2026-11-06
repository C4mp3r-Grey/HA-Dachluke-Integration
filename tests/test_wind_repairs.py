"""Sturmschutz, Reparaturhinweise und Diagnose-Download."""

import json

from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.json import JSONEncoder

from custom_components.dachluke.const import BRIGHTSKY_URL, DOMAIN
from custom_components.dachluke.diagnostics import async_get_config_entry_diagnostics
from tests.test_controller import COVER, HUM, POS, WEATHER, step
from tests.test_weather_sources import _bs, _setup


def _gusty(gust):
    data = _bs()
    data["weather"].update({"wind_gust_speed_10": gust, "wind_speed_10": gust / 2})
    return data


def _issue(hass, entry, key):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{entry.entry_id}")


async def test_storm_blocks_automatic_opening(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_gusty(75))
    c = entry.runtime_data
    assert c.wind_gust() == (75.0, "DWD Musterstadt, 8 km, Böe 10 min")
    assert c.storm_blocked()
    assert any("Sturmböen (75 km/h)" in r for r in c.open_blockers())
    assert c.status == "gesperrt_wetter"
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")
    assert not calls["pos"], "bei Sturm darf die Automatik nicht öffnen"


async def test_storm_closes_open_hatch_and_holds(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_gusty(20))
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")
    await step(hass, freezer, 0.2, POS, "80")
    assert c.mode == "auto"
    aioclient_mock.clear_requests()
    aioclient_mock.get(BRIGHTSKY_URL, json=_gusty(70))
    await c._fetch_brightsky()
    await hass.async_block_till_done()
    assert calls["close"], "bei Sturmböen muss die Luke schließen"
    assert c.counters["close_safety"] == 1
    assert any(p["code"] == "ZU" and "Sturmböen 70 km/h" in p["text"] for p in c.protocol)
    # Wind flaut ab: 30 min Wartezeit, dann wieder frei
    await step(hass, freezer, 0.2, POS, "0")
    aioclient_mock.clear_requests()
    aioclient_mock.get(BRIGHTSKY_URL, json=_gusty(20))
    await c._fetch_brightsky()
    assert not c.storm_now() and c.storm_blocked()
    await step(hass, freezer, 31)
    assert not c.storm_blocked()


async def test_storm_from_weather_entity_in_ms(hass, freezer, aioclient_mock):
    """Ohne Bright Sky: Böe der Wetter-Entität, Einheit wird umgerechnet."""
    entry, calls = await _setup(hass, freezer, aioclient_mock, brightsky=False)
    c = entry.runtime_data
    hass.states.async_set(WEATHER, "cloudy", {"wind_gust_speed": 20, "wind_speed": 9, "wind_speed_unit": "m/s"})
    await hass.async_block_till_done()
    gust, src = c.wind_gust()
    assert round(gust) == 72 and src == "Wetter-Entität, Böe"
    # Handöffnung bei Sturm wird wieder geschlossen
    await step(hass, freezer, 0.2, POS, "50")
    assert calls["close"]
    assert any(p["code"] == "HAND_AUF" and "Sturmböen 72 km/h" in p["text"] for p in c.protocol)


async def test_storm_protection_can_be_disabled(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_gusty(90), wind_enabled=False)
    c = entry.runtime_data
    assert not c.storm_blocked()
    await step(hass, freezer, 0.2, POS, "50")
    assert not calls["close"]


async def test_repair_issue_cover_not_closing(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock)
    c = entry.runtime_data
    await step(hass, freezer, 0.2, POS, "50")  # Handöffnung
    await step(hass, freezer, 16)  # Zeit abgelaufen → Schließbefehl, Luke bleibt aber stehen
    assert calls["close"] and c.mode == "idle"
    await step(hass, freezer, 2)  # erster Prüfzeitpunkt (90 s): zweiter Versuch
    await step(hass, freezer, 3)  # zweiter Prüfzeitpunkt: Hinweis
    issue = _issue(hass, entry, "cover_not_closing")
    assert issue is not None and issue.severity == ir.IssueSeverity.ERROR
    assert issue.translation_placeholders["position"] == "50"
    await step(hass, freezer, 0.2, POS, "0")
    await step(hass, freezer, 3)  # Sicherheitsnetz räumt auf
    assert _issue(hass, entry, "cover_not_closing") is None


async def test_repair_issue_brightsky_after_one_hour(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, status=500)
    c = entry.runtime_data
    assert _issue(hass, entry, "brightsky_unavailable") is None
    await step(hass, freezer, 61)
    await c._fetch_brightsky()
    assert _issue(hass, entry, "brightsky_unavailable") is not None
    aioclient_mock.clear_requests()
    aioclient_mock.get(BRIGHTSKY_URL, json=_bs())
    await c._fetch_brightsky()
    assert _issue(hass, entry, "brightsky_unavailable") is None


async def test_repair_issue_position_sensor_and_unload(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock)
    await step(hass, freezer, 0.1, POS, "unavailable")
    await step(hass, freezer, 6)
    assert _issue(hass, entry, "position_sensor_missing") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _issue(hass, entry, "position_sensor_missing") is None


async def test_diagnostics(hass, freezer, aioclient_mock):
    entry, calls = await _setup(hass, freezer, aioclient_mock, payload=_gusty(30), notify_app_service="notify.mobile_app_handy")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diag, cls=JSONEncoder)  # muss serialisierbar sein
    assert "mobile_app_handy" not in text
    assert diag["settings"]["cover"] == COVER
    assert diag["status"]["wind_gust_kmh"] == 30
    assert diag["sources"]["humidity"]["state"] == "62"
    assert any(p["code"] == "START" for p in diag["stored"]["protocol"])
