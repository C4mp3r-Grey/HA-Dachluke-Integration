"""Ungünstige Abfolgen: erst als Test, dann abgesichert."""

from datetime import timedelta

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import (  # noqa: F401
    BTN_CLOSE, CLIMATE, COVER, HUM, LIGHT, POS, WEATHER, counter, setup, st, step,
)


def codes(c, code):
    return [p["text"] for p in c.protocol if p["code"] == code]


async def _open_auto(hass, freezer):
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    await step(hass, freezer, 0.3, POS, "80")


# 1 ── Neustart: Event-Entität wird mit altem 'press_long_release' wiederhergestellt
async def test_restored_button_state_is_not_a_press(hass, freezer):
    freezer.move_to("2026-11-03 06:00:00+00:00")
    for eid, val in ((HUM, "60"), (POS, "0"), (COVER, "closed"), (WEATHER, "cloudy")):
        hass.states.async_set(eid, val)
    async_mock_service(hass, "cover", "set_cover_position")
    async_mock_service(hass, "cover", "close_cover")
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
                            options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                                     "weather": WEATHER, "button_close": BTN_CLOSE})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Homematic lädt später und stellt den letzten Zustand wieder her
    hass.states.async_set(BTN_CLOSE, "unavailable")
    await hass.async_block_till_done()
    hass.states.async_set(BTN_CLOSE, "2026-11-01T10:00:00+00:00", {"event_type": "press_long_release"})
    await hass.async_block_till_done()
    assert entry.runtime_data.enabled, "wiederhergestellter Zustand darf die Automatik nicht abschalten"


# 2 ── Schließbefehl kommt nicht an (Funk, CCU, Motor)
async def test_close_is_verified_and_retried(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await _open_auto(hass, freezer)
    await step(hass, freezer, 6, HUM, "70")
    await step(hass, freezer, 6, HUM, "62")          # Schließbedingung …
    n = len(calls["close"])
    assert n >= 1
    await step(hass, freezer, 2)                      # … Luke bleibt aber offen
    assert len(calls["close"]) > n, "Schließen wird wiederholt"
    await step(hass, freezer, 3)
    assert codes(c, "FEHLER") and any("schließt nicht" in t for t in codes(c, "FEHLER"))


# 3 ── Öffnungsbefehl kommt nicht an
async def test_failed_open_is_detected(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")          # Befehl geht raus, Luke bleibt zu
    assert c.mode == "auto"
    for _ in range(3):
        await step(hass, freezer, 2)
    assert c.mode == "idle"
    assert any("nicht bewegt" in t for t in codes(c, "FEHLER"))
    assert calls["temp"][-1].data["temperature"] == 21.5, "Heizung zurück"


# 4 ── Feuchtesensor fällt während der Lüftung aus
async def test_humidity_sensor_lost_while_venting(hass, setup, freezer):
    entry, calls = setup
    await _open_auto(hass, freezer)
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "84")          # Duschende
    hass.states.async_set(HUM, "unavailable")
    await hass.async_block_till_done()
    await step(hass, freezer, 25)
    assert calls["close"], "ohne Feuchte nicht endlos verlängern"


# 5 ── Positionssensor fällt während der Lüftung aus
async def test_position_sensor_lost_while_venting(hass, setup, freezer):
    entry, calls = setup
    await _open_auto(hass, freezer)
    hass.states.async_set(POS, "unavailable")
    await hass.async_block_till_done()
    for _ in range(25):
        await step(hass, freezer, 4)
        if calls["close"]:
            break
    c = entry.runtime_data
    assert calls["close"], "Zeitgrenze schließt auch ohne Positionsmeldung"


# 6 ── Thermostat beim Zurückstellen nicht erreichbar
async def test_heating_restore_retried_when_climate_unavailable(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await _open_auto(hass, freezer)
    assert c.heating_lowered
    hass.states.async_set(CLIMATE, "unavailable")
    await step(hass, freezer, 6, HUM, "70")
    await step(hass, freezer, 6, HUM, "62")
    await step(hass, freezer, 0.3, POS, "0")
    assert c.heating_lowered, "nicht als erledigt markieren, solange das Thermostat fehlt"
    hass.states.async_set(CLIMATE, "heat", {"temperature": 15})
    await step(hass, freezer, 3)
    assert not c.heating_lowered and calls["temp"][-1].data["temperature"] == 21.5


# 7 ── Regen flattert um die Schwelle
async def test_rain_flapping_does_not_move_window_constantly(hass, freezer):
    rain = "sensor.regen"
    freezer.move_to("2026-11-03 06:00:00+00:00")
    for eid, val in ((HUM, "60"), (POS, "0"), (COVER, "closed"), (rain, "0.0")):
        hass.states.async_set(eid, val)
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    pos = async_mock_service(hass, "cover", "set_cover_position")
    async_mock_service(hass, "cover", "close_cover")
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
                            options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                                     "weather": WEATHER, "rain_sensor": rain})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "80")
    await step(hass, freezer, 0.3, POS, "80")
    for i in range(6):                                # alle 2 min Regen an/aus
        await step(hass, freezer, 2, rain, "0.2" if i % 2 == 0 else "0.0")
        await step(hass, freezer, 0.3, POS, str(pos[-1].data["position"]))  # Luke folgt dem Befehl
    moves = [cl.data["position"] for cl in pos]
    assert moves.count(80) <= 1, f"nicht ständig wieder aufmachen: {moves}"
    assert 20 in moves, "bei Regen sofort klein"


# 8 ── Automatik aus: Handöffnung darf offen bleiben, Wetter-Sperre schließt trotzdem
async def test_disabled_manual_open_stays_open_but_weather_closes(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await c.async_set_enabled(False)
    await step(hass, freezer, 0.3, POS, "100")
    for _ in range(10):
        await step(hass, freezer, 5)
    assert not calls["close"], "Automatik aus: kein Zeitlimit"
    await step(hass, freezer, 1, WEATHER, "hail", {"temperature": 8})
    assert calls["close"], "Hagel schließt trotzdem"


async def test_reenable_starts_timer_for_open_window(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await c.async_set_enabled(False)
    await step(hass, freezer, 0.3, POS, "100")
    await c.async_set_enabled(True)
    await step(hass, freezer, 16)
    assert calls["close"]
