"""Luke ohne eigenen Positionssensor: Position kommt vom Cover selbst."""

from homeassistant.components.cover import CoverEntityFeature
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.dachluke.const import DEFAULTS, DOMAIN
from tests.test_controller import COVER, HUM, WEATHER, step

FULL = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.SET_POSITION | CoverEntityFeature.STOP
SIMPLE = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP


async def _setup(hass, freezer, features):
    freezer.move_to("2026-11-01 06:00:00+00:00")
    attrs = {"supported_features": features}
    if features & CoverEntityFeature.SET_POSITION:
        attrs["current_position"] = 0
    hass.states.async_set(HUM, "60", {"device_class": "humidity"})
    hass.states.async_set(COVER, "closed", attrs)
    hass.states.async_set(WEATHER, "cloudy", {"temperature": 8, "dew_point": 5})
    calls = {
        "pos": async_mock_service(hass, "cover", "set_cover_position"),
        "open": async_mock_service(hass, "cover", "open_cover"),
        "close": async_mock_service(hass, "cover", "close_cover"),
    }
    options = {**DEFAULTS, "cover": COVER, "humidity_sensor": HUM, "weather": WEATHER}
    options.pop("position_sensor", None)
    entry = MockConfigEntry(domain=DOMAIN, title="Dachluke", unique_id=COVER, data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, calls


async def _shower(hass, freezer):
    await step(hass, freezer, 3, HUM, "70")
    await step(hass, freezer, 2, HUM, "85")


async def test_cover_with_position(hass, freezer):
    entry, calls = await _setup(hass, freezer, FULL)
    c = entry.runtime_data
    assert c.pos_entity == COVER and c.reliable_open() is False
    await _shower(hass, freezer)
    assert calls["pos"] and not calls["open"]
    target = calls["pos"][-1].data["position"]
    await step(hass, freezer, 0.2, COVER, "open", {"supported_features": FULL, "current_position": target})
    assert c.mode == "auto" and c.is_open()
    # Feuchte fällt: schließt, Cover meldet zu
    for value in ("80", "70", "62", "61"):
        await step(hass, freezer, 3, HUM, value)
    assert calls["close"]
    await step(hass, freezer, 0.2, COVER, "closed", {"supported_features": FULL, "current_position": 0})
    assert c.mode in ("idle", "second") and c.reliable_open() is False


async def test_cover_without_position_support(hass, freezer):
    """Nur Auf/Zu: öffnet mit open_cover, Zustand open/closed genügt."""
    entry, calls = await _setup(hass, freezer, SIMPLE)
    c = entry.runtime_data
    assert c.position() == 0
    await _shower(hass, freezer)
    assert calls["open"] and not calls["pos"]
    await step(hass, freezer, 0.2, COVER, "open", {"supported_features": SIMPLE})
    assert c.mode == "auto" and c.position() == 100


async def test_manual_open_detected_from_cover(hass, freezer):
    entry, calls = await _setup(hass, freezer, FULL)
    c = entry.runtime_data
    await step(hass, freezer, 0.2, COVER, "open", {"supported_features": FULL, "current_position": 40})
    assert c.mode == "manual" and c.counters["open_manual"] == 1
    await step(hass, freezer, 16)
    assert calls["close"]


async def test_cover_unavailable_raises_issue(hass, freezer):
    from homeassistant.helpers import issue_registry as ir
    entry, calls = await _setup(hass, freezer, FULL)
    await step(hass, freezer, 0.1, COVER, "unavailable")
    await step(hass, freezer, 6)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"position_sensor_missing_{entry.entry_id}")
    assert issue is not None and issue.translation_placeholders["entity"] == COVER


async def test_position_sensor_entity_follows_cover(hass, freezer):
    from tests.test_controller import st
    entry, calls = await _setup(hass, freezer, FULL)
    assert st(hass, "position") == "0.0"
    await step(hass, freezer, 0.2, COVER, "open", {"supported_features": FULL, "current_position": 35})
    assert st(hass, "position") == "35.0"
