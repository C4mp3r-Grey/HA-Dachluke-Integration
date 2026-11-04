"""Herkunft einer Handbedienung: Benutzer, Automation, außerhalb von HA."""

from homeassistant.core import Context

from tests.test_controller import COVER, POS, setup, step  # noqa: F401


def hand(entry, code="HAND_AUF"):
    return [p["text"] for p in entry.runtime_data.protocol if p["code"] == code][-1]


async def test_user_from_dashboard(hass, setup, freezer, hass_admin_user):
    entry, calls = setup
    await hass.services.async_call("cover", "set_cover_position", {"entity_id": COVER, "position": 60},
                                   blocking=True, context=Context(user_id=hass_admin_user.id))
    await step(hass, freezer, 0.2, POS, "60")
    assert f"über HA: Benutzer {hass_admin_user.name}" in hand(entry)
    await hass.services.async_call("cover", "close_cover", {"entity_id": COVER},
                                   blocking=True, context=Context(user_id=hass_admin_user.id))
    await step(hass, freezer, 0.2, POS, "0")
    assert f"über HA: Benutzer {hass_admin_user.name}" in hand(entry, "HAND_ZU")


async def test_automation_name(hass, setup, freezer):
    from pytest_homeassistant_custom_component.common import async_mock_service
    entry, calls = setup
    async_mock_service(hass, "cover", "open_cover")
    ctx = Context()
    hass.bus.async_fire("automation_triggered", {"name": "Bad morgens lüften", "entity_id": "automation.bad"}, context=ctx)
    await hass.async_block_till_done()
    await hass.services.async_call("cover", "open_cover", {"entity_id": COVER}, blocking=True, context=Context(parent_id=ctx.id))
    await step(hass, freezer, 0.2, POS, "100")
    assert "Automation „Bad morgens lüften“" in hand(entry)


async def test_outside_ha(hass, setup, freezer):
    entry, calls = setup
    await step(hass, freezer, 0.2, POS, "100")
    assert "außerhalb von HA" in hand(entry)


async def test_own_commands_not_attributed(hass, setup, freezer):
    entry, calls = setup
    c = entry.runtime_data
    await c.async_vent_now()
    await step(hass, freezer, 0.2, POS, "80")
    assert "Jetzt lüften" in hand(entry)
