"""Erkennung von Hand-Schließen und Schließen-Taste."""

from tests.test_controller import BTN_CLOSE, HUM, POS, counter, setup, st, step  # noqa: F401


async def test_manual_open_then_manual_close(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 1, POS, "100")
    await step(hass, freezer, 3, POS, "0")
    assert counter(hass, "close_manual") == 1
    assert st(hass, "status") == "pause"
    codes = [p["code"] for p in entry.runtime_data.protocol]
    assert "HAND_ZU" in codes


async def test_auto_open_then_manual_close(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 3, POS, "0")
    assert counter(hass, "close_manual") == 1


async def test_close_button_short_logged(hass, setup, freezer):
    entry, _ = setup
    await step(hass, freezer, 1, BTN_CLOSE, "2026-11-01T06:01:00+00:00", {"event_type": "press_short"})
    assert any(p["code"] == "TASTE" for p in entry.runtime_data.protocol)


async def test_no_takeover_when_automation_off(hass, setup, freezer):
    """Protokoll 09.11. 07:44: Automatik aus, Dusche bei Handöffnung – keine Übernahme, kein Zeitlimit."""
    entry, calls = setup
    c = entry.runtime_data
    await c.async_set_enabled(False)
    await step(hass, freezer, 0.2, POS, "50")
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")
    assert c.mode == "manual" and c.vent_end is None
    assert not any(p["code"] == "UEBERNAHME" for p in c.protocol)
    await step(hass, freezer, 120)
    assert not calls["close"]


async def test_position_bounce_while_closing_is_not_manual_open(hass, setup, freezer):
    """Protokoll 13.11. 13:49: Nach dem Schließbefehl meldete der BROLL 0 % und dann noch einmal 100 %."""
    entry, calls = setup
    c = entry.runtime_data
    await step(hass, freezer, 0.2, POS, "100")  # Handöffnung
    assert c.counters["open_manual"] == 1
    await step(hass, freezer, 15.5)  # Zeitablauf → Schließbefehl
    assert calls["close"]
    await step(hass, freezer, 0.05, POS, "0")    # Ziel gemeldet
    await step(hass, freezer, 0.1, POS, "100")   # alte Position noch einmal
    await step(hass, freezer, 0.4, POS, "0")     # wirklich zu
    assert c.counters["open_manual"] == 1
    assert c.mode == "idle"
    assert sum(1 for p in c.protocol if p["code"] == "HAND_AUF") == 1


async def test_real_reopen_after_close_still_detected(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await step(hass, freezer, 0.2, POS, "100")
    await step(hass, freezer, 15.5)
    await step(hass, freezer, 0.5, POS, "0")
    await step(hass, freezer, 1.5, POS, "100")  # 90 s später wirklich wieder auf
    assert c.counters["open_manual"] == 2 and c.mode == "manual"
