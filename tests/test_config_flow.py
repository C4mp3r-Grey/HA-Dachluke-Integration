from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dachluke.const import DOMAIN


async def test_user_flow_and_options(hass: HomeAssistant):
    hass.states.async_set("sensor.bad_feuchte", "60", {"device_class": "humidity"})
    hass.states.async_set("sensor.dachluke_ch3", "0")
    hass.states.async_set("cover.dachluke", "closed")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Dachluke",
            "cover": "cover.dachluke",
            "position_sensor": "sensor.dachluke_ch3",
            "humidity_sensor": "sensor.bad_feuchte",
            "require_light": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.options["rise_threshold"] == 8.0
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "heating"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "heating_enabled": True,
            "heating_vent_temp": 15,
            "heating_restore": "previous",
            "heating_normal_temp": 22,
            "frost_enabled": False,
            "frost_threshold": -5,
            "frost_position": 10,
            "frost_duration": 8,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"climate": "climate_required"}
