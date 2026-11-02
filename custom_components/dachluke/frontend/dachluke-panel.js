// Seitenleisten-Seite der Integration "Dachluke Badentlüftung".
// Reines Web Component ohne Build-Schritt. Farben kommen aus dem HA-Theme.

const STATUS_TEXT = {
  bereit: "Bereit",
  lueftet_auto: "Lüftet (Automatik)",
  lueftet_manuell: "Lüftet (von Hand)",
  nachlueften: "Zweites Nachlüften",
  pause: "Pause",
  deaktiviert: "Automatik aus",
  gesperrt_alarm: "Gesperrt (Alarm)",
  gesperrt_wetter: "Gesperrt (Wetter)",
  sensor_fehlt: "Sensor fehlt",
};
const COUNTER_TEXT = [
  ["open_auto", "Automatisch geöffnet"],
  ["open_manual", "Von Hand geöffnet"],
  ["showers", "Duschen erkannt"],
  ["showers_missed", "Duschen ohne Öffnen"],
  ["close_humidity", "Zu wegen Feuchte"],
  ["close_timer", "Zu nach Zeitablauf"],
  ["close_stall", "Zu: Trocknung stagniert"],
  ["close_manual", "Von Hand geschlossen"],
  ["close_safety", "Zu wegen Wetter/Alarm"],
  ["sensor_failures", "Sensorausfälle"],
];
const RANGES = [[6, "6 h"], [24, "24 h"], [72, "3 Tage"], [168, "7 Tage"]];
const COLORS = {
  hum: "#2a78d6", room: "#00838f", rise: "#eb6834", pos: "#1baf7a", light: "#eda100",
  fan: "#6250d6", auto: "#1baf7a", manual: "#e87ba4", pause: "#8a959b", warn: "#d03b3b",
};

// Kleiner YAML-Schreiber für die Dashboard-Vorlage (Objekte, Listen, Strings, Zahlen, Booleans)
function yamlScalar(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  const t = String(v);
  if (/^[A-Za-z0-9_.\-\/äöüÄÖÜß ]+$/.test(t) && !/^(true|false|null|yes|no|on|off|~|-?\d[\d.]*)$/i.test(t) && !/^\s|\s$/.test(t) && !t.startsWith("- ")) return t;
  return JSON.stringify(t);
}
function toYaml(v, ind = 0) {
  const pad = " ".repeat(ind);
  if (Array.isArray(v)) {
    if (!v.length) return pad + "[]";
    return v.map(item => {
      if (item && typeof item === "object") {
        const inner = toYaml(item, ind + 2).replace(/^\s+/, "");
        return `${pad}- ${inner}`;
      }
      return `${pad}- ${yamlScalar(item)}`;
    }).join("\n");
  }
  if (v && typeof v === "object") {
    return Object.entries(v).filter(([, x]) => x !== undefined).map(([k, x]) => {
      if (typeof x === "string" && x.includes("\n")) {
        return `${pad}${k}: |-\n` + x.split("\n").map(l => " ".repeat(ind + 2) + l).join("\n");
      }
      if (x && typeof x === "object" && (Array.isArray(x) ? x.length : Object.keys(x).length)) {
        return `${pad}${k}:\n${toYaml(x, ind + 2)}`;
      }
      return `${pad}${k}: ${Array.isArray(x) ? "[]" : (x && typeof x === "object") ? "{}" : yamlScalar(x)}`;
    }).join("\n");
  }
  return pad + yamlScalar(v);
}

class DachlukePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hours = 24;
    this._entry = null;
    this._info = [];
    this._history = null;
    this._lastFetch = 0;
    this._filter = "";
    this._built = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this._built) this._build();
    this._menu && ((this._menu.hass = hass), (this._menu.narrow = this._narrow));
    if (first) this._load();
    else this._renderLive();
  }
  set narrow(v) { this._narrow = v; if (this._menu) this._menu.narrow = v; }
  set panel(p) { this._panel = p; }

  async _load() {
    try {
      this._info = await this._hass.callWS({ type: "dachluke/info" });
    } catch (e) {
      this._error(`Die Integration antwortet nicht: ${e.message || e}`);
      return;
    }
    if (!this._info.length) { this._error("Noch keine Dachluke eingerichtet. Einstellungen → Geräte & Dienste → Integration hinzufügen → Dachluke Badentlüftung."); return; }
    if (!this._entry || !this._info.find(i => i.entry_id === this._entry)) this._entry = this._info[0].entry_id;
    this._renderAll();
    this._fetchHistory();
    clearInterval(this._timer);
    this._timer = setInterval(() => this._refresh(), 60000);
  }

  async _refresh() {
    try { this._info = await this._hass.callWS({ type: "dachluke/info" }); } catch (e) { return; }
    this._renderAll();
    if (Date.now() - this._lastFetch > 5 * 60000) this._fetchHistory();
  }

  disconnectedCallback() { clearInterval(this._timer); }

  get _cur() { return this._info.find(i => i.entry_id === this._entry); }

  _build() {
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100%;font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif)}
        .bar{display:flex;align-items:center;gap:8px;height:56px;padding:0 max(12px,env(safe-area-inset-left,0px));background:var(--app-header-background-color,var(--primary-color));color:var(--app-header-text-color,#fff);font-size:20px}
        .bar select{margin-left:auto;font:inherit;font-size:14px;background:transparent;color:inherit;border:1px solid currentColor;border-radius:6px;padding:4px 6px}
        main{max-width:1100px;margin:0 auto;padding:16px max(16px,env(safe-area-inset-left,0px));display:grid;gap:16px}
        .card{background:var(--card-background-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);padding:16px;display:flex;flex-direction:column;gap:12px;min-width:0}
        h2{margin:0;font-size:16px;font-weight:600}
        .row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
        .status{font-size:24px;font-weight:600}
        .muted{color:var(--secondary-text-color);font-size:13px}
        .pill{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--divider-color)}
        .pill.warn{border-color:${COLORS.warn}}
        button{font:inherit;font-size:13px;padding:6px 12px;border-radius:8px;border:1px solid var(--primary-color);background:transparent;color:var(--primary-color);cursor:pointer}
        button.on{background:var(--primary-color);color:var(--text-primary-color,#fff)}
        button:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
        .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
        .tile{border-top:1px solid var(--divider-color);padding-top:6px}
        .tile b{display:block;font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}
        .tile span{font-size:12px;color:var(--secondary-text-color)}
        .chart{position:relative}
        .chart svg{display:block;width:100%;height:auto}
        .tt{position:absolute;top:8px;pointer-events:none;background:var(--card-background-color);border:1px solid var(--divider-color);border-radius:8px;padding:8px;font-size:12px;min-width:170px;box-shadow:0 2px 8px rgba(0,0,0,.2)}
        .tt div{display:flex;justify-content:space-between;gap:10px}
        .key{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--secondary-text-color)}
        .key i{display:inline-block;width:12px;height:8px;border-radius:2px;margin-right:4px;vertical-align:middle}
        .tw{overflow-x:auto;max-height:420px;overflow-y:auto;border:1px solid var(--divider-color);border-radius:8px}
        table{border-collapse:collapse;width:100%;font-size:13px}
        th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--divider-color);vertical-align:top}
        th{position:sticky;top:0;background:var(--card-background-color);font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--secondary-text-color)}
        td.t{white-space:nowrap;font-variant-numeric:tabular-nums}
        td.c{white-space:nowrap;font-family:monospace;font-size:12px}
        textarea{width:100%;min-height:220px;font-family:monospace;font-size:12px;background:var(--primary-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:8px;padding:8px;box-sizing:border-box}
        select#yamlvariant{font:inherit;font-size:13px;padding:6px 8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--primary-background-color);color:var(--primary-text-color)}
        input[type=search]{font:inherit;font-size:13px;padding:6px 8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--primary-background-color);color:var(--primary-text-color)}
        details summary{cursor:pointer;font-weight:600}
        .err{color:${COLORS.warn}}
      </style>
      <div class="bar"><span id="menu"></span><span>Dachluke</span><select id="entry" hidden aria-label="Dachluke wählen"></select></div>
      <main>
        <section class="card" id="live"></section>
        <section class="card">
          <div class="row" style="justify-content:space-between"><h2>Analyse</h2><span class="muted" id="since"></span></div>
          <div class="tiles" id="tiles"></div>
        </section>
        <section class="card">
          <div class="row" style="justify-content:space-between"><h2>Verlauf</h2><div class="row" id="ranges"></div></div>
          <div class="key">
            <span><i style="background:${COLORS.hum}"></i>Feuchte Dusche</span><span><i style="background:${COLORS.room}"></i>Feuchte Raum</span><span><i style="background:${COLORS.rise}"></i>Anstieg 5 min</span>
            <span><i style="background:${COLORS.pos}"></i>Luke</span><span><i style="background:${COLORS.light}"></i>Licht</span>
            <span><i style="background:${COLORS.fan}"></i>Lüfter</span><span><i style="background:${COLORS.manual}"></i>Lüftung von Hand</span>
            <span><i style="background:${COLORS.pause}"></i>Pause/aus</span><span><i style="background:${COLORS.warn}"></i>Dusche ohne Öffnen</span>
          </div>
          <div class="chart" id="chart"><div class="tt" id="tt" hidden></div><p class="muted" id="chartmsg">Verlauf wird geladen…</p></div>
        </section>
        <section class="card">
          <div class="row" style="justify-content:space-between"><h2>Protokoll</h2>
            <div class="row"><input type="search" id="filter" placeholder="Filtern, z. B. VERPASST" aria-label="Protokoll filtern"><button id="copylog">Als CSV kopieren</button></div></div>
          <div class="tw"><table id="log"></table></div>
        </section>
        <section class="card">
          <details><summary>Dashboard-YAML für ein eigenes Dashboard</summary>
            <p class="muted">Neues Dashboard anlegen → Bearbeiten → Raw-Konfigurationseditor → Inhalt ersetzen. Die Entity-IDs sind deine echten.</p>
            <div class="row">
              <label class="muted" for="yamlvariant">Variante</label>
              <select id="yamlvariant">
                <option value="custom">Mit Bubble Card, Mushroom und mini-graph-card</option>
                <option value="standard">Nur Standardkarten</option>
              </select>
              <button id="copyyaml">YAML kopieren</button><span class="muted" id="copied"></span>
            </div>
            <textarea id="yaml" readonly aria-label="Dashboard-YAML"></textarea>
          </details>
        </section>
      </main>`;
    const r = this.shadowRoot;
    if (customElements.get("ha-menu-button")) {
      this._menu = document.createElement("ha-menu-button");
      r.getElementById("menu").append(this._menu);
    }
    r.getElementById("entry").addEventListener("change", e => { this._entry = e.target.value; this._renderAll(); this._fetchHistory(); });
    r.getElementById("filter").addEventListener("input", e => { this._filter = e.target.value.toLowerCase(); this._renderLog(); });
    r.getElementById("copylog").addEventListener("click", () => this._copy(this._logCsv(), "copylog"));
    r.getElementById("yamlvariant").addEventListener("change", () => this._renderYaml());
    r.getElementById("copyyaml").addEventListener("click", () => this._copy(r.getElementById("yaml").value, "copyyaml"));
    const rg = r.getElementById("ranges");
    RANGES.forEach(([h, label]) => {
      const b = document.createElement("button"); b.textContent = label; b.dataset.h = h;
      b.addEventListener("click", () => { this._hours = h; this._fetchHistory(); this._renderRanges(); });
      rg.append(b);
    });
    this._renderRanges();
    addEventListener("resize", () => this._renderChart());
  }

  _error(msg) { this.shadowRoot.getElementById("live").innerHTML = `<p class="err">${msg}</p>`; }

  _renderRanges() {
    this.shadowRoot.querySelectorAll("#ranges button").forEach(b => b.classList.toggle("on", +b.dataset.h === this._hours));
  }

  _renderAll() {
    const sel = this.shadowRoot.getElementById("entry");
    sel.hidden = this._info.length < 2;
    sel.innerHTML = this._info.map(i => `<option value="${i.entry_id}" ${i.entry_id === this._entry ? "selected" : ""}>${i.title}</option>`).join("");
    this._renderLive(); this._renderTiles(); this._renderLog(); this._renderYaml(); this._renderChart();
  }

  _st(eid) { return eid && this._hass.states[eid]; }

  _renderLive() {
    const c = this._cur; if (!c) return;
    const e = c.entities, s = this._st(e.status);
    const status = s ? s.state : c.status;
    const blockers = (s && s.attributes.hindernisse_oeffnen) || c.blockers || [];
    const roomSt = c.sources.room_humidity ? this._st(c.sources.room_humidity) : null;
    const roomVal = roomSt ? (roomSt.entity_id.startsWith("climate.") ? roomSt.attributes.current_humidity : roomSt.state) : null;
    const hum = this._st(c.sources.humidity), pos = this._st(c.sources.position);
    const rise = this._st(e.humidity_rise), end = this._st(e.vent_end), ah = this._st(e.absolute_humidity);
    const ended = s && s.attributes.duschende;
    const auto = this._st(e.automatic), pause = this._st(e.pause);
    const endValid = end && end.state && !["unknown", "unavailable"].includes(end.state);
    const endClock = endValid ? new Date(end.state).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : "";
    const endTxt = status === "lueftet_auto" && !ended
      ? `Dusche läuft – schließt spätestens ${c.settings.max_open} min nach Duschende`
      : endValid ? `Schließt spätestens ${endClock}` : "";
    const showBlockers = ["bereit", "pause", "deaktiviert", "gesperrt_alarm", "gesperrt_wetter", "sensor_fehlt"].includes(status);
    this.shadowRoot.getElementById("live").innerHTML = `
      <div class="row" style="justify-content:space-between">
        <div><div class="status">${STATUS_TEXT[status] || status}</div><div class="muted">${endTxt}</div></div>
        <div class="row">
          <button id="b-auto" class="${auto && auto.state === "on" ? "on" : ""}">Automatik ${auto && auto.state === "on" ? "an" : "aus"}</button>
          <button id="b-pause" class="${pause && pause.state === "on" ? "on" : ""}">Pause ${pause && pause.state === "on" ? "an" : "aus"}</button>
        </div>
      </div>
      <div class="row muted">
        <span>Dusche <b>${hum ? hum.state : "–"} %</b></span>
        ${roomSt ? `<span>Raum <b>${roomVal ?? "–"} %</b></span>` : ""}
        ${ah && !["unknown", "unavailable"].includes(ah.state) ? `<span>absolut <b>${ah.state} g/m³</b></span>` : ""}
        <span>Anstieg <b>${rise ? rise.state : "–"} %/5 min</b> (öffnet ab ${c.settings.rise_threshold})</span>
        <span>Luke <b>${pos ? pos.state : "–"} %</b></span>
        <span>Zielöffnung <b>${c.target} %</b></span>
      </div>
      ${showBlockers ? `<div class="row"><span class="muted">Öffnet jetzt nicht, weil:</span>${blockers.map(b => `<span class="pill ${b !== "Steigung unter Schwelle" ? "warn" : ""}">${b}</span>`).join("") || '<span class="pill">nichts – öffnet beim nächsten Anstieg</span>'}</div>` : ""}`;
    const r = this.shadowRoot;
    r.getElementById("b-auto").onclick = () => this._action(auto && auto.state === "on" ? "disable" : "enable");
    r.getElementById("b-pause").onclick = () => this._action(pause && pause.state === "on" ? "resume" : "pause");
  }

  async _action(action) {
    try { await this._hass.callWS({ type: "dachluke/action", entry_id: this._entry, action }); } catch (e) { this._error(e.message || e); }
    this._refresh();
  }

  _renderTiles() {
    const c = this._cur; if (!c) return;
    this.shadowRoot.getElementById("tiles").innerHTML = COUNTER_TEXT.map(([k, label]) => {
      const st = this._st(c.entities[`count_${k}`]);
      const v = st ? st.state : (c.counters[k] ?? 0);
      return `<div class="tile"><b>${v}</b><span>${label}</span></div>`;
    }).join("") + `<div class="tile"><b>${c.last_duration != null ? Math.round(c.last_duration) + " min" : "–"}</b><span>Dauer letzte Lüftung</span></div>` +
      `<div class="tile"><b>${c.last_shower_minutes != null ? "≈ " + Math.round(c.last_shower_minutes) + " min" : "–"}</b><span>Geschätzte Dauer letztes Duschen</span></div>`;
    const since = c.counters_since ? new Date(c.counters_since).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }) : "";
    this.shadowRoot.getElementById("since").innerHTML = `seit ${since} · <button id="reset">Zurücksetzen</button>`;
    this.shadowRoot.getElementById("reset").onclick = () => this._action("reset");
  }

  _rows() {
    const c = this._cur; if (!c) return [];
    return [...c.protocol].reverse().filter(p => !this._filter || (p.code + " " + p.text).toLowerCase().includes(this._filter));
  }

  _renderLog() {
    const rows = this._rows();
    this.shadowRoot.getElementById("log").innerHTML = `<thead><tr><th>Zeit</th><th>Ereignis</th><th>Details</th></tr></thead><tbody>${
      rows.map(p => `<tr><td class="t">${new Date(p.t).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td><td class="c">${p.code}</td><td>${p.text}</td></tr>`).join("")
      || '<tr><td colspan="3" class="muted">Noch keine Einträge.</td></tr>'}</tbody>`;
  }

  _logCsv() {
    return "zeit;ereignis;details\n" + [...(this._cur?.protocol || [])].map(p => `${p.t};${p.code};"${p.text.replace(/"/g, '""')}"`).join("\n");
  }

  async _copy(text, id) {
    const label = this.shadowRoot.getElementById(id === "copyyaml" ? "copied" : id);
    try { await navigator.clipboard.writeText(text); if (id === "copyyaml") label.textContent = "Kopiert."; else { label.textContent = "Kopiert"; setTimeout(() => (label.textContent = "Als CSV kopieren"), 1500); } }
    catch (e) {
      const ta = this.shadowRoot.getElementById("yaml");
      if (id !== "copyyaml") { ta.value = text; ta.closest("details").open = true; }
      ta.select();
      if (id === "copyyaml") label.textContent = "Bitte markierten Text mit Strg+C kopieren.";
    }
  }

  _renderYaml() {
    const c = this._cur; if (!c) return;
    const variant = this.shadowRoot.getElementById("yamlvariant")?.value || "custom";
    const cfg = variant === "standard" ? this._dashStandard(c) : this._dashCustom(c);
    this.shadowRoot.getElementById("yaml").value = toYaml(cfg) + "\n";
  }

  _dashStandard(c) {
    const e = c.entities, s = c.sources;
    const ids = (...x) => x.flat().filter(Boolean);
    return {
      title: "Dachluke",
      views: [{
        title: "Dachluke", path: "dachluke", type: "sections", max_columns: 3,
        sections: [
          { type: "grid", cards: ids(e.status, e.automatic, e.pause, e.vent_end, s.humidity, e.absolute_humidity, e.humidity_rise).map(id => ({ type: "tile", entity: id })) },
          { type: "grid", cards: [{ type: "entities", title: "Analyse", entities: [
            ...COUNTER_TEXT.filter(([k]) => e[`count_${k}`]).map(([k, label]) => ({ entity: e[`count_${k}`], name: label })),
            ...ids(e.last_duration, e.last_shower_duration, e.reset_counters).map(id => ({ entity: id })),
          ] }] },
          { type: "grid", cards: [
            { type: "history-graph", title: "Feuchte und Luke", hours_to_show: 24, entities: ids(s.humidity, s.room_humidity && s.room_humidity.startsWith("sensor.") ? s.room_humidity : null, e.humidity_rise, s.position).map(id => ({ entity: id })) },
            { type: "history-graph", title: "Zustände", hours_to_show: 24, entities: ids(e.open, s.lights || [], s.fan, e.status).map(id => ({ entity: id })) },
            { type: "logbook", title: "Protokoll", hours_to_show: 168, target: { entity_id: [e.last_event] } },
          ] },
        ],
      }],
    };
  }

  _dashCustom(c) {
    const e = c.entities, s = c.sources;
    const st = e.status, ve = e.vent_end;
    const roomIsClimate = s.room_humidity && s.room_humidity.startsWith("climate.");
    const roomExpr = !s.room_humidity ? null
      : roomIsClimate ? `state_attr('${s.room_humidity}', 'current_humidity')` : `states('${s.room_humidity}')`;
    const venting = `states('${st}') in ['lueftet_auto', 'lueftet_manuell', 'nachlueften']`;
    const sep = (name, icon) => ({ type: "custom:bubble-card", card_type: "separator", name, icon });
    const chip = (content, icon, icon_color, entity) => ({ type: "template", ...(entity ? { entity, tap_action: { action: "more-info" } } : {}), content, icon, icon_color });

    const status = {
      type: "custom:mushroom-template-card",
      entity: st,
      primary: `{{ state_translated('${st}') }}`,
      secondary: [
        `{% set s = '${st}' %}`,
        `{% if ${venting} %}`,
        `{% set e = states('${ve}') %}`,
        `{% if e not in ['unknown', 'unavailable', 'none'] %}Schließt spätestens {{ as_timestamp(e) | timestamp_custom('%H:%M') }}{% else %}Lüftet{% endif %}`,
        `{% else %}`,
        `{% set h = (state_attr(s, 'hindernisse_oeffnen') or []) | reject('eq', 'Steigung unter Schwelle') | list %}`,
        `{{ 'Öffnet beim nächsten Feuchteanstieg' if h | length == 0 else 'Öffnet nicht: ' ~ (h | join(', ')) }}`,
        `{% endif %}`,
      ].join("\n"),
      icon: [
        `{% set s = states('${st}') %}`,
        `{{ 'mdi:window-open-variant' if s in ['lueftet_auto', 'lueftet_manuell', 'nachlueften']`,
        `   else 'mdi:pause-circle' if s == 'pause'`,
        `   else 'mdi:alert-circle' if s in ['gesperrt_alarm', 'gesperrt_wetter', 'sensor_fehlt']`,
        `   else 'mdi:power-off' if s == 'deaktiviert' else 'mdi:window-closed-variant' }}`,
      ].join("\n"),
      icon_color: [
        `{% set s = states('${st}') %}`,
        `{{ 'blue' if s in ['lueftet_auto', 'nachlueften'] else 'purple' if s == 'lueftet_manuell'`,
        `   else 'orange' if s == 'pause' else 'red' if s in ['gesperrt_alarm', 'gesperrt_wetter', 'sensor_fehlt']`,
        `   else 'grey' if s == 'deaktiviert' else 'green' }}`,
      ].join("\n"),
      multiline_secondary: true,
      tap_action: { action: "more-info" },
    };

    const chips = { type: "custom:mushroom-chips-card", alignment: "center", chips: [
      chip(`{{ states('${s.position}') | int(0) }} %`, `{{ 'mdi:window-open-variant' if states('${s.position}') | int(0) > 0 else 'mdi:window-closed-variant' }}`,
        `{{ 'blue' if states('${s.position}') | int(0) > 0 else 'grey' }}`, s.position),
      chip(`Dusche {{ states('${s.humidity}') | int(0) }} %`, "mdi:shower-head", `{{ 'blue' if states('${s.humidity}') | float(0) >= 85 else 'grey' }}`, s.humidity),
      ...(roomExpr ? [chip(`Raum {{ ${roomExpr} | int(0) }} %`, "mdi:home-thermometer", "teal", s.room_humidity)] : []),
      ...(e.absolute_humidity ? [chip(`{{ states('${e.absolute_humidity}') | round(1) }} g/m³`, "mdi:water", "cyan", e.absolute_humidity)] : []),
      chip(`außen {{ state_attr('${st}', 'aussenfeuchte_absolut') | round(1) if state_attr('${st}', 'aussenfeuchte_absolut') is number else '–' }} g/m³`, "mdi:weather-partly-rainy", "grey", s.weather || null),
      ...(s.fan ? [chip(`Lüfter`, "mdi:fan", `{{ 'green' if is_state('${s.fan}', 'on') else 'grey' }}`, s.fan)] : []),
      ...((s.lights || []).slice(0, 1).map(l => chip(`Licht`, "mdi:lightbulb", `{{ 'amber' if is_state('${l}', 'on') else 'grey' }}`, l))),
    ] };

    const toggle = (entity, name, icon) => ({ type: "custom:bubble-card", card_type: "button", button_type: "switch", entity, name, icon });
    const press = (entity, name, icon, visibility) => ({
      type: "custom:bubble-card", card_type: "button", button_type: "name", entity, name, icon,
      tap_action: { action: "perform-action", perform_action: "button.press", target: { entity_id: entity } },
      grid_options: { columns: 6 },
      ...(visibility ? { visibility } : {}),
    });
    // Tasten nur zeigen, wenn sie gerade etwas bewirken
    const isState = (entity, state) => ({ condition: "state", entity, state });
    const notState = (entity, state_not) => ({ condition: "state", entity, state_not });
    const whenClosed = e.open ? [isState(e.open, "off"), notState(st, "gesperrt_alarm")] : null;
    const whenManual = [isState(st, "lueftet_manuell")];
    const whenOpen = e.open ? [isState(e.open, "on")] : null;
    const controls = [
      sep("Steuerung", "mdi:gesture-tap"),
      ...(e.vent_now ? [press(e.vent_now, "Jetzt lüften", "mdi:window-open-variant", whenClosed)] : []),
      ...(e.vent_now ? [press(e.vent_now, `${c.settings.manual_duration ?? 15} min verlängern`, "mdi:timer-plus-outline", whenManual)] : []),
      ...(e.stop_venting ? [press(e.stop_venting, "Lüftung beenden", "mdi:window-closed-variant", whenOpen)] : []),
      { type: "custom:bubble-card", card_type: "button", button_type: "slider", entity: s.cover, name: "Öffnung", icon: "mdi:window-shutter-open", grid_options: { columns: "full" } },
      { type: "custom:bubble-card", card_type: "cover", entity: s.cover, name: "Dachluke", grid_options: { columns: "full" } },
      ...(s.fan ? [{ ...toggle(s.fan, "Lüfter", "mdi:fan"), grid_options: { columns: 6 } }] : []),
      ...((s.lights || []).slice(0, 1).map(l => ({ ...toggle(l, "Licht", "mdi:lightbulb"), grid_options: { columns: 6 } }))),
    ];

    const RANGES_DASH = [["6h", "6 h", 6, 12], ["24h", "24 h", 24, 6], ["3d", "3 Tage", 72, 2], ["7d", "7 Tage", 168, 1]];
    const humidityGraph = (hours, pph) => ({
      type: "custom:mini-graph-card", name: "Feuchte", icon: "mdi:water-percent",
      hours_to_show: hours, points_per_hour: pph, line_width: 2, hour24: true,
      // Feuchte mit Abstand zur Achse; Luke genau 0–100 %
      lower_bound: 30, upper_bound: 100, lower_bound_secondary: 0, upper_bound_secondary: 100,
      show: { labels: true, labels_secondary: true, legend: true, fill: false, points: false },
      entities: [
        { entity: s.humidity, name: "Dusche", color: "#2a78d6" },
        ...(s.room_humidity ? [{ entity: s.room_humidity, ...(roomIsClimate ? { attribute: "current_humidity" } : {}), name: "Raum", color: "#00838f" }] : []),
        { entity: s.position, name: "Luke", color: "#1baf7a", y_axis: "secondary", show_fill: true, aggregate_func: "max", smoothing: false },
      ],
    });
    const absGraph = (hours, pph) => e.absolute_humidity ? {
      type: "custom:mini-graph-card", name: "Absolute Feuchte", icon: "mdi:water", unit: "g/m³",
      hours_to_show: hours, points_per_hour: pph, line_width: 2, hour24: true,
      // Feste Untergrenze 0, damit niedrige Außenwerte nicht auf der Achse kleben; oben weich
      lower_bound: 0, upper_bound: "~20",
      show: { labels: true, legend: true, fill: false, points: false },
      entities: [
        { entity: e.absolute_humidity, name: "Raum", color: "#00838f" },
        { entity: st, attribute: "schliessen_bei_absolut", name: "Schließziel", color: "#eb6834", smoothing: false },
        { entity: st, attribute: "aussenfeuchte_absolut", name: "Außen", color: "#8a959b" },
      ],
    } : null;
    const statesGraph = (hours) => ({ type: "history-graph", title: "Zustände", hours_to_show: hours,
      entities: [e.open, ...(s.lights || []), s.fan, st].filter(Boolean).map(entity => ({ entity })) });
    const sel = e.chart_range;
    const rangeChips = sel ? [{
      type: "custom:mushroom-chips-card", alignment: "center", grid_options: { columns: "full" },
      chips: RANGES_DASH.map(([key, label]) => ({
        type: "template", content: label, icon: "mdi:clock-outline",
        icon_color: `{{ 'blue' if is_state('${sel}', '${key}') else 'grey' }}`,
        tap_action: { action: "perform-action", perform_action: "select.select_option", target: { entity_id: sel }, data: { option: key } },
      })),
    }] : [];
    // Pro Zeitraum eine Variante, sichtbar nur wenn ausgewählt (ohne Auswahl-Entität: 24 h)
    const perRange = (make) => !sel ? [make(24, 6)].filter(Boolean)
      : RANGES_DASH.map(([key, , h, pph]) => {
          const card = make(h, pph);
          return card && { type: "conditional", conditions: [{ condition: "state", entity: sel, state: key }], card, grid_options: { columns: "full" } };
        }).filter(Boolean);

    const analysis = { type: "entities", title: "Seit letztem Zurücksetzen", show_header_toggle: false, entities: [
      ...COUNTER_TEXT.filter(([k]) => e[`count_${k}`]).map(([k, label]) => ({ entity: e[`count_${k}`], name: label })),
      { type: "divider" },
      ...[[e.last_duration, "Dauer letzte Lüftung"], [e.last_shower_duration, "Dauer letztes Duschen (geschätzt)"]].filter(([id]) => id).map(([entity, name]) => ({ entity, name })),
      ...(e.reset_counters ? [{ entity: e.reset_counters, name: "Analyse zurücksetzen" }] : []),
    ] };


    return {
      title: "Dachluke",
      views: [{
        title: "Dachluke", path: "dachluke", icon: "mdi:window-open-variant", type: "sections", max_columns: 3,
        sections: [
          { type: "grid", cards: [
            sep("Jetzt", "mdi:window-open-variant"),
            { ...status, grid_options: { columns: "full" } },
            { ...chips, grid_options: { columns: "full" } },
            { ...toggle(e.automatic, "Automatik", "mdi:robot"), grid_options: { columns: 6 } },
            { ...toggle(e.pause, "Pause", "mdi:pause"), grid_options: { columns: 6 } },
            ...controls,
          ] },
          { type: "grid", cards: [
            sep("Verlauf", "mdi:chart-line"),
            ...rangeChips,
            ...perRange(humidityGraph),
            ...perRange(absGraph),
            ...perRange(statesGraph),
          ] },
          { type: "grid", cards: [
            sep("Analyse", "mdi:clipboard-text-search-outline"),
            { ...analysis, grid_options: { columns: "full" } },
            { type: "logbook", title: "Protokoll", hours_to_show: 168, target: { entity_id: [e.last_event] }, grid_options: { columns: "full" } },
          ] },
        ],
      }],
    };
  }

  async _fetchHistory() {
    const c = this._cur; if (!c) return;
    const s = c.sources, e = c.entities;
    const roomId = s.room_humidity && s.room_humidity.startsWith("sensor.") ? s.room_humidity : null;
    const ids = [s.humidity, roomId, s.position, e.humidity_rise, e.status, s.fan, ...(s.lights || [])].filter(Boolean);
    const end = new Date(), start = new Date(end - this._hours * 3600000);
    this._range = [start.getTime(), end.getTime()];
    try {
      this._history = await this._hass.callWS({
        type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
        entity_ids: ids, minimal_response: true, no_attributes: true, significant_changes_only: false,
      });
      this._roomSeries = [];
      if (s.room_humidity && s.room_humidity.startsWith("climate.")) {
        // Thermostat liefert die Feuchte nur als Attribut: Verlauf mit Attributen laden
        const full = await this._hass.callWS({
          type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
          entity_ids: [s.room_humidity], minimal_response: false, no_attributes: false, significant_changes_only: false,
        });
        let last = null;
        this._roomSeries = ((full && full[s.room_humidity]) || []).map(x => {
          const a = x.a || x.attributes;
          if (a && a.current_humidity != null) last = a.current_humidity;
          return { t: ((x.lu ?? x.lc) || 0) * 1000, s: last };
        }).filter(x => x.t && x.s != null).sort((a, b) => a.t - b.t);
      }
      this._lastFetch = Date.now();
    } catch (err) {
      this.shadowRoot.getElementById("chartmsg").textContent = `Verlauf nicht verfügbar: ${err.message || err}`;
      return;
    }
    this._renderChart();
  }

  _series(eid) {
    const raw = (this._history && this._history[eid]) || [];
    return raw.map(x => ({ t: ((x.lu ?? x.lc) || 0) * 1000, s: x.s })).filter(x => x.t).sort((a, b) => a.t - b.t);
  }

  _renderChart() {
    const c = this._cur, box = this.shadowRoot.getElementById("chart");
    if (!c || !this._history || !box) return;
    this.shadowRoot.getElementById("chartmsg").hidden = true;
    box.querySelector("svg")?.remove();
    const [T0, T1] = this._range, W = Math.max(320, box.clientWidth || 900), L = 38, R = 10;
    const x = t => L + (Math.max(T0, Math.min(T1, t)) - T0) / (T1 - T0) * (W - L - R);
    const css = n => getComputedStyle(this).getPropertyValue(n).trim() || "#888";
    const ink = css("--secondary-text-color"), grid = css("--divider-color");
    const s = c.sources, e = c.entities;
    const room = !s.room_humidity ? [] : s.room_humidity.startsWith("sensor.") ? this._series(s.room_humidity) : (this._roomSeries || []);
    const hum = this._series(s.humidity), rise = this._series(e.humidity_rise), pos = this._series(s.position);
    const status = this._series(e.status), fan = s.fan ? this._series(s.fan) : [];
    const lights = (s.lights || []).map(id => this._series(id));
    const at = (ser, t) => { let v = null; for (const p of ser) { if (p.t <= t) v = p.s; else break; } return v; };
    const num = v => (v == null || isNaN(parseFloat(v)) ? null : parseFloat(v));
    const g1 = 14, h1 = 110, g2 = g1 + h1 + 26, h2 = 70, g3 = g2 + h2 + 26, h3 = 46, g4 = g3 + h3 + 24, lane = 12;
    const lanes = [["Licht", t => lights.some(l => at(l, t) === "on") ? COLORS.light : null],
                   ["Lüfter", t => (fan.length && at(fan, t) === "on") ? COLORS.fan : null],
                   ["Modus", t => { const v = at(status, t); return v === "lueftet_auto" || v === "nachlueften" ? COLORS.auto : v === "lueftet_manuell" ? COLORS.manual : (v === "pause" || v === "deaktiviert") ? COLORS.pause : v && v.startsWith("gesperrt") ? COLORS.warn : null; }]];
    const H = g4 + lanes.length * (lane + 4) + 22;
    const yOf = (v, g, h, min, max) => g + h - (Math.max(min, Math.min(max, v)) - min) / (max - min) * h;
    const stepPath = (ser, g, h, min, max) => {
      let d = "", last = null;
      for (const p of ser) { const v = num(p.s); if (v == null) { last = null; continue; }
        const X = x(p.t).toFixed(1), Y = yOf(v, g, h, min, max).toFixed(1);
        d += last == null ? `M${X},${Y}` : `H${X}V${Y}`; last = Y; }
      if (last != null) d += `H${x(T1).toFixed(1)}`;
      return d;
    };
    const axis = (g, h, min, max, ticks, unit, label) => `<text x="${L}" y="${g - 4}" fill="${ink}" font-size="10">${label}</text>` +
      ticks.map(v => { const y = yOf(v, g, h, min, max); return `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${grid}"/><text x="${L - 4}" y="${y + 3}" text-anchor="end" fill="${ink}" font-size="9">${v}${unit}</text>`; }).join("");
    const thr = c.settings.rise_threshold;
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Verlauf Feuchte, Anstieg, Luke und Zustände">`;
    svg += axis(g1, h1, 40, 100, [40, 60, 80, 100], "%", "Feuchte");
    svg += `<path d="${stepPath(hum, g1, h1, 40, 100)}" fill="none" stroke="${COLORS.hum}" stroke-width="2"/>`;
    if (room.length) svg += `<path d="${stepPath(room, g1, h1, 40, 100)}" fill="none" stroke="${COLORS.room}" stroke-width="2" stroke-dasharray="6 3"/>`;
    svg += axis(g2, h2, -10, 20, [-10, 0, 10, 20], "", "Anstieg %/5 min");
    const yt = yOf(thr, g2, h2, -10, 20);
    svg += `<line x1="${L}" x2="${W - R}" y1="${yt}" y2="${yt}" stroke="${COLORS.rise}" stroke-dasharray="4 4" opacity=".7"/><text x="${W - R}" y="${yt - 3}" text-anchor="end" fill="${ink}" font-size="9">öffnet ab ${thr}</text>`;
    svg += `<path d="${stepPath(rise, g2, h2, -10, 20)}" fill="none" stroke="${COLORS.rise}" stroke-width="2"/>`;
    svg += axis(g3, h3, 0, 100, [0, 100], "%", "Luke");
    const pp = stepPath(pos, g3, h3, 0, 100);
    if (pp) svg += `<path d="${pp}V${g3 + h3}H${x(pos.length ? pos[0].t : T0)}Z" fill="${COLORS.pos}" fill-opacity=".3" stroke="${COLORS.pos}" stroke-width="2"/>`;
    // Verpasste Duschen aus dem Protokoll markieren
    const missed = (c.protocol || []).filter(p => p.code === "DUSCHE_VERPASST").map(p => new Date(p.t).getTime() - 10 * 60000).filter(t => t >= T0);
    missed.forEach(t => { svg += `<rect x="${x(t)}" y="${g1}" width="${Math.max(3, x(t + 10 * 60000) - x(t))}" height="${g3 + h3 - g1}" fill="${COLORS.warn}" opacity=".12"/>`; });
    lanes.forEach(([label, colorAt], i) => {
      const y = g4 + i * (lane + 4);
      svg += `<text x="${L - 4}" y="${y + lane - 2}" text-anchor="end" fill="${ink}" font-size="9">${label}</text><rect x="${L}" y="${y}" width="${W - L - R}" height="${lane}" fill="${grid}" opacity=".4"/>`;
      const stepMs = Math.max(60000, (T1 - T0) / 600);
      let on = null, col = null;
      for (let t = T0; t <= T1 + stepMs; t += stepMs) {
        const v = t <= T1 ? colorAt(t) : null;
        if (v !== col) { if (col) svg += `<rect x="${x(on).toFixed(1)}" y="${y}" width="${Math.max(2, x(t) - x(on)).toFixed(1)}" height="${lane}" rx="2" fill="${col}"/>`; on = t; col = v; }
      }
    });
    const ticks = W < 520 ? 4 : this._hours <= 72 ? 6 : 7;
    for (let i = 0; i <= ticks; i++) {
      const t = T0 + (T1 - T0) * i / ticks, d = new Date(t);
      const lab = this._hours <= 24 ? d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit" });
      svg += `<text x="${x(t)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === ticks ? "end" : "middle"}" fill="${ink}" font-size="9">${lab}</text>`;
    }
    svg += `<line id="xh" x1="0" x2="0" y1="${g1}" y2="${H - 18}" stroke="${ink}" opacity="0"/><rect id="hit" x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/></svg>`;
    box.insertAdjacentHTML("beforeend", svg);
    const el = box.querySelector("svg"), xh = el.querySelector("#xh"), tt = this.shadowRoot.getElementById("tt");
    const move = ev => {
      const r = el.getBoundingClientRect(), px = (ev.clientX - r.left) * W / r.width;
      if (px < L || px > W - R) { tt.hidden = true; xh.setAttribute("opacity", 0); return; }
      const t = T0 + (px - L) / (W - L - R) * (T1 - T0);
      xh.setAttribute("x1", px); xh.setAttribute("x2", px); xh.setAttribute("opacity", .5);
      const st = at(status, t);
      tt.innerHTML = `<b>${new Date(t).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" })}</b>` +
        [["Feuchte Dusche", (at(hum, t) ?? "–") + " %"], ...(room.length ? [["Feuchte Raum", (at(room, t) ?? "–") + " %"]] : []), ["Anstieg", at(rise, t) ?? "–"], ["Luke", (at(pos, t) ?? "–") + " %"],
         ["Licht", lights.some(l => at(l, t) === "on") ? "an" : "aus"], ["Lüfter", fan.length ? at(fan, t) ?? "–" : "–"], ["Status", STATUS_TEXT[st] || st || "–"]]
          .map(([a, b]) => `<div><span>${a}</span><span>${b}</span></div>`).join("");
      tt.hidden = false;
      const bx = box.getBoundingClientRect(); let lx = ev.clientX - bx.left + 12; if (lx + 190 > bx.width) lx -= 204; tt.style.left = Math.max(0, lx) + "px";
    };
    el.addEventListener("pointermove", move); el.addEventListener("pointerdown", move);
    el.addEventListener("pointerleave", () => { tt.hidden = true; xh.setAttribute("opacity", 0); });
  }
}

customElements.define("dachluke-panel", DachlukePanel);
