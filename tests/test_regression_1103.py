"""03.11. 08:24: Automatik öffnete, ein 0→0-Update wurde als 'von Hand geschlossen'
gewertet, die Luke blieb danach den ganzen Tag offen."""

from tests.test_controller import HUM, POS, counter, setup, st, step  # noqa: F401


async def test_stale_zero_update_is_not_a_manual_close(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")          # öffnet automatisch
    assert calls["pos"] and c.mode == "auto"
    # Positionssensor meldet erneut 0 (nur Attribut geändert), dann fährt die Luke
    await step(hass, freezer, 0.05, POS, "0")
    hass.states.async_set(POS, "0", {"last_seen": "x"})
    await hass.async_block_till_done()
    assert c.mode == "auto", "kein HAND_ZU durch Attribut-Update"
    assert not any(p["code"] == "HAND_ZU" for p in c.protocol)
    await step(hass, freezer, 0.3, POS, "100")
    assert c.mode == "auto" and c.vent_end is not None


async def test_watchdog_adopts_unknown_open_window(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    # Integration hält sich für 'idle', die Luke ist aber offen
    c._pending = ("open", __import__("homeassistant.util.dt", fromlist=["utcnow"]).utcnow())
    await step(hass, freezer, 0.1, POS, "100")
    c.mode = "idle"
    c._pending = None
    await step(hass, freezer, 3)
    assert c.mode == "manual"
    assert any(p["code"] == "KORREKTUR" for p in c.protocol)
    await step(hass, freezer, 16)
    assert calls["close"], "spätestens nach der Handöffnungs-Dauer zu"
