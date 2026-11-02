"""Tasten 'Jetzt lüften' und 'Lüftung beenden'."""

from homeassistant.helpers import entity_registry as er

from tests.test_controller import COVER, POS, WEATHER, setup, st, step  # noqa: F401


def _button(hass, entry, key):
    return er.async_get(hass).async_get_entity_id("button", "dachluke", f"{entry.entry_id}_{key}")


async def test_vent_now_and_stop(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await hass.services.async_call("button", "press", {"entity_id": _button(hass, entry, "vent_now")}, blocking=True)
    await hass.async_block_till_done()
    assert calls["pos"][-1].data["position"] == 80
    await step(hass, freezer, 0.3, POS, "80")
    auf = [p["text"] for p in c.protocol if p["code"] == "HAND_AUF"][-1]
    assert "Jetzt lüften" in auf
    assert st(hass, "status") == "lueftet_manuell"
    await hass.services.async_call("button", "press", {"entity_id": _button(hass, entry, "stop_venting")}, blocking=True)
    await hass.async_block_till_done()
    assert calls["close"]
    await step(hass, freezer, 0.3, POS, "0")
    assert st(hass, "status") == "pause"
    zu = [p["text"] for p in c.protocol if p["code"] == "HAND_ZU"][-1]
    assert "Lüftung beenden" in zu


async def test_vent_now_respects_weather(hass, setup, freezer):
    entry, calls = setup
    hass.states.async_set(WEATHER, "hail", {"temperature": 8})
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {"entity_id": _button(hass, entry, "vent_now")}, blocking=True)
    await hass.async_block_till_done()
    assert calls["pos"][-1].data["position"] == 20
