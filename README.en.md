# Dachluke Badentlüftung – roof hatch bathroom ventilation

🇩🇪 [Deutsche Version](README.md)

Home Assistant integration that vents a bathroom through a motorised roof hatch or roof window. It was developed with a Homematic IP **HmIP-BROLL** and works with any `cover` entity. It combines three things:

1. **Control**: opens after a shower, closes again, and takes weather, storm, frost, heating, alarm and buttons into account.
2. **Analysis**: counts and logs every opening, closing and shower with its reason, including showers where the hatch did not open.
3. **Sidebar page “Dachluke”**: status, counters, history and log. It also generates a dashboard YAML with your real entity IDs.

Everything is configured in the UI. You don't need helpers, statistics sensors or YAML packages.

> [!WARNING]
> **Beta.** So far it has been used day to day on exactly one hatch (HmIP-BROLL with position sensor). The defaults are tuned for that one bathroom. A hatch that opens automatically can cause damage in rain, storm or frost. Watch it for the first days, check the settings and don't rely on the automation blindly. Use at your own risk, see [License, liability and origin](#license-liability-and-origin).

> [!NOTE]
> The sidebar page, settings and repair notices are available in English. The **log, notifications and voice output are German only**. The log codes (e.g. `AUTO_AUF`, `ZU`) are listed below.

---

## Installation via HACS

1. HACS → ⋮ → **Custom repositories** → URL of this repository, type **Integration**.
2. Download “Dachluke Badentlüftung” and restart Home Assistant.
3. **Settings → Devices & services → Add integration → Dachluke Badentlüftung**.
4. Choose the cover and the humidity sensor. Position sensor, weather and lights are optional.
5. Then go to **Configure** for the other sections: venting, weather, heating, buttons, safety, notifications.

Without HACS, copy `custom_components/dachluke` to `/config/custom_components/` and restart.

### Which hatch? Position sensor or not

| Drive | Position sensor | Behaviour |
|---|---|---|
| Cover that reports its position (`current_position`), e.g. many Velux, Somfy or Zigbee drives | leave empty | position comes from the cover |
| Cover with open/close only (no set position) | leave empty | opens fully (`open_cover`); opening width and rain limitation don't apply |
| HmIP-BROLL, or a cover that only reports its target | set it | position comes from the separate sensor in 0–100 % |

With HmIP-BROLL, the cover (channel 4) tends to report the target value. Channel 3 reports the real position. To get it: Homematic(IP) Local → open the HmIP-BROLL → **Unignore parameters** → channel 3 → `LEVEL` → restart.

Only HmIP-BROLL with a position sensor has been used on real hardware so far. The other variants are covered by automated tests, but have not been tried on a real device. Feedback is very welcome.

### Two humidity sensors (recommended)

- **Shower humidity:** a fast sensor close to the shower. It detects the start and end of the shower and may saturate at 100 %.
- **Room humidity (optional):** e.g. the wall thermostat, away from the shower. If set, room humidity and temperature decide when to close, when drying has stalled, and the second venting. You can also pick the thermostat (`climate`) itself, its `current_humidity` attribute is then used.

## How it decides

- **Opening:** relative humidity rises by at least 8 % within 5 minutes (configurable). Optionally the light must be on. The opening width depends on the weather: 80 % normally, 20 % in rain or when the weather is restricted.
- **Shower end:** humidity has dropped 3 % from its peak. While the shower is running the hatch stays open, up to a hard limit of 90 minutes.
- **Closing**, after the shower has ended, as soon as one of these applies:
  - humidity is back near the pre-shower value. With a temperature sensor this uses absolute humidity (+1 g/m³), otherwise relative humidity (+3 %).
  - if the room was already more humid than usual: the learned typical room humidity (median of quiet periods over the last 3 days), but never below outdoor absolute humidity + 0.5 g/m³.
  - drying has stalled (less than 1 % drop in 10 min).
  - the venting time is over (20 min after the shower ended). It extends in 5-minute steps while humidity is still falling.
  - the room gets too cold (below 18 °C).
- **Manual opening** runs for 15 minutes. If someone showers meanwhile, the automation takes over. With the automation switched off, a manual opening stays open until you close it.
- **Second venting** (optional, off by default): 25 minutes after closing, if humidity is still above 60 %, the hatch opens again for 2 minutes.
- **Fan** is switched on with the hatch and off again only if the integration switched it on.
- **Heating** (optional) can be lowered while venting and restored afterwards. Thermostats with their own window-open function (e.g. Homematic IP with a linked window contact) ignore this. The integration detects that and stops interfering.

## Safety net

| Case | Behaviour |
|---|---|
| Position update without movement (e.g. 0 → 0) | ignored |
| Hatch open but no venting known | adopted as a manual opening within about 4 minutes, closes after the manual duration |
| Hatch does not open after the command | venting ends, heating restored, notification |
| Hatch does not close after the command | second attempt after 90 s, then a critical notification and a repair notice |
| Humidity sensor or position unavailable | time limits still close; automatic opening blocked |
| Rain flapping around the threshold | immediately small, wide again only after 15 min without rain |
| Storm gusts above the threshold (default 60 km/h) | closes, also after a manual opening and with the automation off; reopens automatically only 30 min after the last gust |

## Storm protection

Under *Configure → Weather and opening width*: **Storm protection** (default on) and **Close at gusts of** (default 60 km/h). This is a guideline only, adjust it to your hatch.

Gust source, in this order:

1. measured gust of the last 10 min at the nearest DWD station, if *DWD measurements* are enabled. These measurements cover Germany only.
2. gust of the weather entity (`wind_gust_speed`)
3. mean wind of the weather entity (`wind_speed`), if no gust is provided

Weather entities usually provide forecast or model values, not measurements. The status attribute `boeen_quelle` shows which source is active.

## Repairs and diagnostics

Persistent problems appear under **Settings → System → Repairs** and disappear once the cause is fixed:

- hatch does not close
- hatch does not open
- humidity sensor missing or position unknown for more than 5 min
- thermostat ignores the venting temperature
- DWD measurements unavailable for more than 1 h

**Download diagnostics** (integration page → ⋮) gives you a JSON file with settings, current state, all source entities, the learned reference, counters and the full log. The notification service name is redacted. Please attach this file to bug reports, but check it first: it contains your entity IDs.

## Entities

- `sensor.…_status` with the attribute `hindernisse_oeffnen` (why it would not open right now)
- hatch position, humidity rise in 5 min, absolute humidity, humidity at the coldest wall, baseline, venting end, last venting duration, estimated last shower duration, last event
- counters (diagnostic): opened automatically or manually; closed by humidity, timer, stalled drying, cold, manually, weather or alarm; showers detected; showers without opening; sensor failures
- `binary_sensor.…_open`, `switch.…_automatic`, `switch.…_pause`, `select.…_chart_range`
- buttons: **Vent now**, **Stop venting**, **Reset analysis**

## Log codes

`AUTO_AUF` opened automatically · `HAND_AUF` / `HAND_ZU` opened or closed manually (with source: user, automation, script, or outside HA) · `DUSCHE` / `DUSCHE_ENDE` shower start and end · `DUSCHE_VERPASST` shower without opening · `ZU` closed (with reason) · `VERLAENGERT` venting extended · `BILANZ` summary after venting · `WETTER` weather or storm · `LUEFTER` fan · `HEIZUNG` heating · `KORREKTUR` safety net corrected the state · `FEHLER` error · `AUSFALL` sensor unavailable · `NACHLUEFTEN` second venting · `ENDLAGE` hatch stopped (position and travel time) · `UEBERNAHME` automation takes over a manual opening · `WIDERSPRUCH` contact and position disagree · `ALARM` alarm · `TASTE` button press · `WETTERQUELLE` weather source changed · `PAUSE`, `PAUSE_ENDE`, `AKTIV`, `DEAKTIV`, `RESET`, `START`, `NEUSTART`, `EINSTELLUNGEN`

## Updates

Every version gets a GitHub release, which HACS shows as an update. On every push, GitHub runs the tests against the pinned and the latest HA version, plus hassfest and the HACS validation. They also run every Monday. See [CHANGELOG.md](CHANGELOG.md) (German).

## Privacy

The integration works locally. The one exception is **DWD measurements (Bright Sky)**. If you enable them, it queries `api.brightsky.dev` every 10 minutes and sends your Home Assistant coordinates rounded to two decimals (about 1 km), plus your IP address as with any web request. Bright Sky is a free third-party service and not part of this project. The option is off by default.

## License, liability and origin

- License: [GNU GPL v3.0](LICENSE). You may use, modify and share the code. Shared modifications must stay under the same license, be marked as changed and keep the original copyright notice.
- The software is provided as is, without warranty, to the extent permitted by law (see sections 15 and 16 of the license).
- Developed by C4mp3r-Grey with extensive help from Claude (Anthropic). The domain logic, requirements and day-to-day testing come from the hatch's owner, and a large part of the code was written by the AI. The commits are marked accordingly.

## Development

```
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest -p no:logging
```
