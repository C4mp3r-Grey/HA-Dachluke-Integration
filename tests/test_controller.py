"""Ablauftests mit der Home-Assistant-Testumgebung."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.dachluke.const import DEFAULTS, DOMAIN

HUM = "sensor.bad_feuchte"
POS = "sensor.dachluke_ch3"
COVER = "cover.dachluke"
LIGHT = "light.bad"
WEATHER = "weather.forecast_home"
BTN_OPEN = "event.dachluke_ch1"
BTN_CLOSE = "event.dachluke_ch2"
CLIMATE = "climate.bad"


@pytest.fixture
async def setup(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    freezer.move_to("2026-11-01 06:00:00+00:00")
    hass.states.async_set(HUM, "60", {"device_class": "humidity"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed", {"current_position": 0})
    hass.states.async_set(LIGHT, "off")
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8, "dew_point": 5})
    hass.states.async_set(BTN_OPEN, "2026-10-31T10:00:00+00:00", {"event_type": "press_short"})
    hass.states.async_set(BTN_CLOSE, "2026-10-31T10:00:00+00:00", {"event_type": "press_short"})
    hass.states.async_set(CLIMATE, "heat", {"temperature": 21.5})
    calls = {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "close": async_mock_service(hass, "cover", "close_cover"),
        "temp": [],
    }

    async def _set_temp(call):
        # Wie ein Thermostat ohne eigene Fenster-auf-Funktion: übernimmt den Sollwert
        calls["temp"].append(call)
        st = hass.states.get(CLIMATE)
        hass.states.async_set(CLIMATE, st.state if st else "heat", {**(st.attributes if st else {}), "temperature": call.data["temperature"]})

    hass.services.async_register("climate", "set_temperature", _set_temp)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dachluke",
        unique_id=COVER,
        data={},
        options={
            **DEFAULTS,
            "cover": COVER,
            "position_sensor": POS,
            "humidity_sensor": HUM,
            "weather": WEATHER,
            "lights": [LIGHT],
            "button_open": BTN_OPEN,
            "button_close": BTN_CLOSE,
            "heating_enabled": True,
            "climate": CLIMATE,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def step(hass, freezer, minutes, entity=None, value=None, attrs=None):
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    if entity:
        hass.states.async_set(entity, value, attrs or {})
    await hass.async_block_till_done()


def eid(hass, key, domain="sensor"):
    from homeassistant.helpers import entity_registry as er
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")


def st(hass, key, domain="sensor"):
    return hass.states.get(eid(hass, key, domain)).state


def counter(hass, name):
    return int(st(hass, f"count_{name}"))


async def test_entities_created(hass, setup):
    assert st(hass, "status") == "bereit"
    assert st(hass, "automatic", "switch") == "on"


async def test_auto_open_and_close_on_baseline(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    assert calls["pos"][-1].data["position"] == 80
    assert calls["temp"][-1].data["temperature"] == 15.0
    await step(hass, freezer, 0.2, POS, "80")
    assert st(hass, "status") == "lueftet_auto"
    assert counter(hass, "open_auto") == 1
    assert counter(hass, "open_manual") == 0
    # Feuchte fällt zurück auf Ausgangswert 60 + 3
    await step(hass, freezer, 6, HUM, "70")
    assert not calls["close"]
    await step(hass, freezer, 6, HUM, "62.5")
    assert len(calls["close"]) == 1
    assert calls["temp"][-1].data["temperature"] == 21.5  # vorheriger Sollwert
    await step(hass, freezer, 0.2, POS, "0")
    assert counter(hass, "close_humidity") == 1
    assert counter(hass, "close_manual") == 0
    assert st(hass, "status") == "bereit"


async def test_light_not_required_by_default(hass, setup, freezer):
    _, calls = setup
    hass.states.async_set(LIGHT, "off")
    await step(hass, freezer, 3, HUM, "70")
    assert calls["pos"], "öffnet auch bei ausgeschaltetem Licht"


async def test_manual_open_gets_timer_and_ignores_low_humidity(hass, setup, freezer):
    _, calls = setup
    await step(hass, freezer, 1, POS, "100")  # von Hand, z. B. Dashboard
    assert st(hass, "status") == "lueftet_manuell"
    await step(hass, freezer, 3, HUM, "55")
    assert not calls["close"], "Handöffnung schließt nicht wegen niedriger Feuchte"
    await step(hass, freezer, 13)
    assert len(calls["close"]) == 1
    assert counter(hass, "close_timer") == 1


async def test_repeated_short_close_presses_all_detected(hass, setup, freezer):
    entry, _ = setup
    controller = entry.runtime_data
    for i in range(3):
        await step(hass, freezer, 15, BTN_CLOSE, f"2026-11-01T06:{10 + i:02d}:00+00:00", {"event_type": "press_short"})
        assert controller.paused(), f"Druck {i + 1} erkannt"
    msgs = [p["text"] for p in controller.protocol if p["code"] == "TASTE"]
    assert len(msgs) == 3


async def test_long_close_disables_and_long_open_enables(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 1, BTN_CLOSE, "2026-11-01T06:01:00+00:00", {"event_type": "press_long_release"})
    assert st(hass, "automatic", "switch") == "off"
    await step(hass, freezer, 3, HUM, "75")
    assert not calls["pos"]
    await step(hass, freezer, 1, BTN_OPEN, "2026-11-01T06:05:00+00:00", {"event_type": "press_long_release"})
    assert st(hass, "automatic", "switch") == "on"


async def test_missed_shower_is_logged(hass, setup, freezer):
    entry, calls = setup
    controller = entry.runtime_data
    await controller.async_set_pause(True)
    await step(hass, freezer, 3, HUM, "66")
    assert not calls["pos"]
    await step(hass, freezer, 11)
    assert counter(hass, "showers_missed") == 1
    missed = [p for p in controller.protocol if p["code"] == "DUSCHE_VERPASST"]
    assert missed and "Pause" in missed[-1]["text"]


async def test_state_survives_reload(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    await step(hass, freezer, 0.2, POS, "80")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert st(hass, "status") == "lueftet_auto"
    # Höchstwert und Timer überstehen den Neustart: Duschende erkennen, dann 20 min Nachlüften
    await step(hass, freezer, 1, HUM, "68")
    assert entry.runtime_data.shower_end is not None
    # Feuchte bleibt bei 68 %: nach 10 min ohne Abfall schließt die Stagnationsprüfung
    await step(hass, freezer, 9)
    assert not calls["close"]
    await step(hass, freezer, 2)
    assert calls["close"]
    assert counter(hass, "close_stall") == 1


async def test_weather_blocked_closes(hass, setup, freezer):
    _, calls = setup
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 1, WEATHER, "hail", {"temperature": 8})
    assert calls["close"]
    assert counter(hass, "close_safety") == 1


async def test_websocket_info_and_action(hass, setup, hass_ws_client):
    entry, _ = setup
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "dachluke/info"})
    msg = await client.receive_json()
    assert msg["success"]
    info = msg["result"][0]
    assert info["entities"]["status"].startswith("sensor.")
    assert info["sources"]["humidity"] == HUM
    await client.send_json({"id": 2, "type": "dachluke/action", "entry_id": entry.entry_id, "action": "disable"})
    msg = await client.receive_json()
    assert msg["success"]
    assert entry.runtime_data.enabled is False


async def test_panel_registered(hass, setup):
    from homeassistant.components.frontend import DATA_PANELS

    assert "dachluke" in hass.data[DATA_PANELS]


async def test_alarm_closes_and_blocks(hass, setup, freezer):
    entry, calls = setup
    hass.config_entries.async_update_entry(entry, options={**entry.options, "alarm_entity": "alarm_control_panel.haus"})
    await hass.async_block_till_done()
    hass.states.async_set("alarm_control_panel.haus", "disarmed")
    await step(hass, freezer, 3, HUM, "66")
    await step(hass, freezer, 2, HUM, "73")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 1, "alarm_control_panel.haus", "armed_away")
    assert calls["close"]
    await step(hass, freezer, 0.2, POS, "0")
    assert st(hass, "status") == "gesperrt_alarm"
