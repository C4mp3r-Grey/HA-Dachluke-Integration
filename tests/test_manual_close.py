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
