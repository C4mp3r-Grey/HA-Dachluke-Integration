"""Lüfter ergänzt die offene Luke."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, step  # noqa: F401

FAN = "fan.hmip_bs2_bad_c542_4_lufter"


async def _setup(hass, freezer, fan_state="off", **extra):
    freezer.move_to("2026-11-02 11:00:00+00:00")
    hass.states.async_set(HUM, "80", {"device_class": "humidity"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(FAN, fan_state)
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8})
    calls = {"on": async_mock_service(hass, "fan", "turn_on"), "off": async_mock_service(hass, "fan", "turn_off"),
             "close": async_mock_service(hass, "cover", "close_cover"),
             "pos": async_mock_service(hass, "cover", "set_cover_position")}
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
                            options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                                     "weather": WEATHER, "fan": FAN, **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def test_manual_open_turns_fan_on_and_off(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await step(hass, freezer, 1, POS, "100")          # von Hand, Licht aus, 80 %
    assert len(calls["on"]) == 1
    hass.states.async_set(FAN, "on")
    await step(hass, freezer, 5, POS, "0")            # von Hand geschlossen
    assert len(calls["off"]) == 1


async def test_fan_off_after_timer(hass, freezer):
    entry, calls = await _setup(hass, freezer)
    await step(hass, freezer, 1, POS, "100")
    hass.states.async_set(FAN, "on")
    await step(hass, freezer, 16)
    assert calls["close"] and len(calls["off"]) == 1


async def test_fan_already_running_is_left_alone(hass, freezer):
    entry, calls = await _setup(hass, freezer, fan_state="on")
    await step(hass, freezer, 1, POS, "100")
    await step(hass, freezer, 5, POS, "0")
    assert not calls["on"] and not calls["off"]


async def test_fan_control_disabled(hass, freezer):
    entry, calls = await _setup(hass, freezer, fan_control=False)
    await step(hass, freezer, 1, POS, "100")
    assert not calls["on"]
