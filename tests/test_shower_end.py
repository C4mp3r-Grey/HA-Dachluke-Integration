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
    entry, calls = await _setup(hass, freezer, stall_enabled=False)
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


async def test_stalled_drying_closes_early(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await _shower_start(hass, freezer)
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "84")  # Duschende (T)
    await step(hass, freezer, 3, HUM, "72")  # T+3
    await step(hass, freezer, 3, HUM, "69")  # T+6, Außenluft feucht: bleibt stehen
    await step(hass, freezer, 5)  # T+11
    await step(hass, freezer, 4)  # T+15
    assert not calls["close"], "der Abfall von 72 auf 69 % liegt noch im Beobachtungszeitraum"
    await step(hass, freezer, 3)  # T+18
    assert calls["close"], "10 min ohne nennenswerten Abfall → vor Ablauf der 20 min geschlossen"
    assert counter(hass, "close_stall") == 1
    assert any("stagniert" in p["text"] for p in entry.runtime_data.protocol)


async def test_steady_drying_is_not_stall(hass, freezer):
    entry, calls = await _setup(hass, freezer, stall_minutes=10, stall_delta=1.0)
    await _shower_start(hass, freezer)
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "86")  # Duschende
    for v in ("84", "82", "80", "78", "76", "74"):
        await step(hass, freezer, 3, HUM, v)
    assert not calls["close"], "fällt stetig um ~2 %/3 min – keine Stagnation"


async def test_stall_can_be_disabled(hass, freezer):
    entry, calls = await _setup(hass, freezer, stall_enabled=False)
    await _shower_start(hass, freezer)
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "84")
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 14)
    assert not calls["close"], "ohne Stagnationsprüfung bleibt die Luke offen"
    await step(hass, freezer, 4)
    assert calls["close"]
    assert counter(hass, "close_timer") == 1


async def test_rise_during_venting_is_not_a_missed_shower(hass, freezer):
    """Protokoll 06.11.: erneuter Anstieg bei offener Luke zählte als 'Dusche ohne Öffnen'."""
    entry, calls = await _setup(hass, freezer, stall_enabled=False)
    c = entry.runtime_data
    await _shower_start(hass, freezer)
    for v in ("90", "93", "95"):
        await step(hass, freezer, 2, HUM, v)
    await step(hass, freezer, 11)  # Prüfung der ersten Dusche
    await step(hass, freezer, 2, HUM, "90")  # Duschende
    await step(hass, freezer, 3, HUM, "86")
    await step(hass, freezer, 3, HUM, "84")
    await step(hass, freezer, 2, HUM, "92")  # zweite Person, Luke noch offen
    await step(hass, freezer, 2, HUM, "97")
    await step(hass, freezer, 11)
    assert counter(hass, "showers_missed") == 0
    # zweite Person mehr als 5 min nach Duschende: eigene Dusche (seit 1.16.2), aber nicht „verpasst“
    assert counter(hass, "showers") == 2
    assert any(p["code"] == "DUSCHE" and "während der Lüftung" in p["text"] for p in c.protocol)


async def test_short_pause_keeps_shower_start(hass, freezer):
    """Wasser kurz aus: geschätzte Duschdauer zählt ab dem ersten Anstieg."""
    entry, calls = await _setup(hass, freezer, stall_enabled=False)
    c = entry.runtime_data
    await _shower_start(hass, freezer)
    start = c.shower_start
    for v in ("90", "93", "95"):
        await step(hass, freezer, 2, HUM, v)
    await step(hass, freezer, 1, HUM, "91")  # Duschende erkannt
    assert c.shower_end is not None
    await step(hass, freezer, 1, HUM, "99")  # nach 1 min wieder steigend
    assert c.shower_end is None and c.shower_start == start
    await step(hass, freezer, 4, HUM, "100")
    await step(hass, freezer, 2, HUM, "95")
    assert c.last_shower_minutes is not None and c.last_shower_minutes >= 10
    assert any(p["code"] == "DUSCHE" and "Dusche läuft weiter" in p["text"] for p in c.protocol)


async def test_second_person_counts_and_restarts_hard_cap(hass, freezer):
    """Protokoll 08.11.: zweite Dusche 10 min nach der ersten – eigene Dusche, Obergrenze ab ihrem Beginn."""
    entry, calls = await _setup(hass, freezer, stall_enabled=False, hard_cap=60)
    c = entry.runtime_data
    await _shower_start(hass, freezer)
    opened = c.opened_at
    for v in ("90", "95", "97"):
        await step(hass, freezer, 2, HUM, v)
    await step(hass, freezer, 2, HUM, "92")  # Duschende
    assert c.shower_end is not None
    await step(hass, freezer, 4, HUM, "88")
    await step(hass, freezer, 6, HUM, "86")  # 10 min Pause
    await step(hass, freezer, 2, HUM, "96")  # zweite Person
    assert c.shower_end is None
    assert counter(hass, "showers") == 2
    assert c._cap_end() > opened + __import__("datetime").timedelta(minutes=60)
    assert any(p["code"] == "DUSCHE" and "neue Dusche" in p["text"] for p in c.protocol)
    await step(hass, freezer, 11)
    assert counter(hass, "showers_missed") == 0


async def _plateau_after_shower(hass, freezer, **extra):
    """Protokoll 06./08.11.: nach dem Duschen bleibt die Feuchte deutlich über dem Ziel stehen."""
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 7, "humidity": 85})
    entry, calls = await _setup(hass, freezer, temperature_sensor=TEMP, stall_enabled=True, hard_cap=60, **extra)
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 7, "humidity": 85})
    await _shower_start(hass, freezer)
    for v in ("90", "95", "97"):
        await step(hass, freezer, 2, HUM, v)
    await step(hass, freezer, 2, HUM, "92")  # Duschende
    await step(hass, freezer, 2, HUM, "80")
    await step(hass, freezer, 2, HUM, "76")
    for _ in range(8):  # 16 min Plateau bei 75 % (≈ 13.7 g/m³ bei 21 °C)
        await step(hass, freezer, 2, HUM, "75")
    return entry, calls


async def test_plateau_far_above_target_keeps_venting(hass, freezer):
    entry, calls = await _plateau_after_shower(hass, freezer)
    c = entry.runtime_data
    dry, why = c.drier_outside()
    assert dry, why
    assert not calls["close"], "Außenluft deutlich trockener: nicht wegen Stagnation schließen"
    await step(hass, freezer, 10)
    assert not calls["close"]
    assert any(p["code"] == "VERLAENGERT" and "Noch zu feucht" in p["text"] for p in c.protocol)
    await step(hass, freezer, 30)  # harte Obergrenze 60 min greift
    assert calls["close"] and counter(hass, "close_stall") == 0


async def test_plateau_closes_for_stall_when_option_off(hass, freezer):
    entry, calls = await _plateau_after_shower(hass, freezer, vent_until_dry=False)
    assert calls["close"]
    assert counter(hass, "close_stall") == 1
