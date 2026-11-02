"""Protokoll-Inhalte für die Auswertung."""

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, POS, WEATHER, st, step  # noqa: F401

CONTACT = "binary_sensor.dachluke_kontakt"
BTN_OPEN = "event.dachluke_ch1"


async def _setup(hass, freezer, weather="cloudy", **extra):
    freezer.move_to("2026-11-01 06:00:00+00:00")
    hass.states.async_set(HUM, "65", {"device_class": "humidity"})
    hass.states.async_set(POS, "0")
    hass.states.async_set(COVER, "closed")
    hass.states.async_set(CONTACT, "off")
    hass.states.async_set(BTN_OPEN, "2026-10-31T10:00:00+00:00", {"event_type": "press_short"})
    hass.states.async_set(WEATHER, weather, {"temperature": 7.5, "humidity": 90, "dew_point": 6})
    async_mock_service(hass, "cover", "set_cover_position")
    async_mock_service(hass, "cover", "close_cover")
    entry = MockConfigEntry(
        domain=DOMAIN, title="Dachluke", unique_id=COVER, data={},
        options={**DEFAULTS, "cover": COVER, "position_sensor": POS, "humidity_sensor": HUM,
                 "weather": WEATHER, "contact_sensor": CONTACT, "button_open": BTN_OPEN, **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def texts(entry, code):
    return [p["text"] for p in entry.runtime_data.protocol if p["code"] == code]


async def test_start_and_reason_and_shower_duration(hass, freezer):
    entry = await _setup(hass, freezer, weather="rainy")
    assert texts(entry, "START") and "Version" in texts(entry, "START")[0]
    await step(hass, freezer, 3, HUM, "70")   # 06:03 Anstieg beginnt
    await step(hass, freezer, 2, HUM, "82")   # 06:05 öffnet
    auf = texts(entry, "AUTO_AUF")[0]
    assert "auf 20 % – Öffnungsweite: eingeschränktes Wetter (rainy)" in auf
    assert "außen rainy 7.5 °C 90 %" in auf
    for v in ("92", "95", "95.5", "95"):      # Plateau bis 06:17
        await step(hass, freezer, 3, HUM, v)
    await step(hass, freezer, 3, HUM, "90")   # 06:20 Duschende erkannt
    ende = texts(entry, "DUSCHE_ENDE")[0]
    assert "Duschen geschätzt 14 min" in ende, ende
    assert entry.runtime_data.last_shower_minutes == 14
    assert hass.states.get("sensor.dachluke_last_shower_duration_estimated").state == "14.0"


async def test_balance_on_close(hass, freezer):
    entry = await _setup(hass, freezer, stall_enabled=False)
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "82")
    await step(hass, freezer, 0.2, POS, "80")
    await step(hass, freezer, 3, HUM, "90")
    await step(hass, freezer, 3, HUM, "80")
    await step(hass, freezer, 6, HUM, "67")
    bilanz = texts(entry, "BILANZ")
    assert bilanz and "Grund feuchte" in bilanz[0] and "max. 80 %" in bilanz[0] and "Höchstwert 90 %" in bilanz[0]


async def test_manual_source_detected(hass, freezer):
    entry = await _setup(hass, freezer)
    await step(hass, freezer, 1, BTN_OPEN, "2026-11-01T06:01:00+00:00", {"event_type": "press_short"})
    await step(hass, freezer, 0.3, POS, "100")
    assert "per Taste am Gerät" in texts(entry, "HAND_AUF")[0]
    await step(hass, freezer, 5, POS, "0")
    await step(hass, freezer, 5, POS, "40")
    assert "ohne erkannten Tastendruck" in texts(entry, "HAND_AUF")[1]


async def test_contact_mismatch_only_after_standstill(hass, freezer):
    entry = await _setup(hass, freezer)
    hass.states.async_set(COVER, "opening")
    await step(hass, freezer, 0.05, POS, "7")
    await step(hass, freezer, 0.5)               # fährt noch
    assert not texts(entry, "WIDERSPRUCH")
    hass.states.async_set(COVER, "open")
    await step(hass, freezer, 0.05, POS, "100")
    await step(hass, freezer, 0.1, CONTACT, "on")  # Kontakt meldet verzögert
    await step(hass, freezer, 1)
    assert not texts(entry, "WIDERSPRUCH")
    assert texts(entry, "ENDLAGE") and "100 %" in texts(entry, "ENDLAGE")[-1]


async def test_contact_mismatch_reported_when_persistent(hass, freezer):
    entry = await _setup(hass, freezer)
    await step(hass, freezer, 0.05, POS, "50")
    await step(hass, freezer, 0.5)
    assert not texts(entry, "WIDERSPRUCH")
    await step(hass, freezer, 0.5)
    assert texts(entry, "WIDERSPRUCH")


async def test_settings_change_logged(hass, freezer):
    entry = await _setup(hass, freezer)
    hass.config_entries.async_update_entry(entry, options={**entry.options, "rise_threshold": 6.0})
    await hass.async_block_till_done()
    changed = texts(entry, "EINSTELLUNGEN")
    assert changed and "rise_threshold: 8.0 → 6.0" in changed[0]
