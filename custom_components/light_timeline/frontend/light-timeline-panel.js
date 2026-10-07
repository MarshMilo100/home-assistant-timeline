// Light Timeline panel. No build step or external dependencies.
// Interpolation below mirrors interpolation.py; keep both in sync.

const DAY = 86400;

const EASE = {
  linear: (t) => t,
  ease_in: (t) => t * t,
  ease_out: (t) => 1 - (1 - t) ** 2,
  ease_in_out: (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2),
  sine: (t) => (1 - Math.cos(Math.PI * t)) / 2,
  step: () => 0,
};

const LOG_K = 5;
const CURVE = {
  linear: [(p) => p, (o) => o],
  square: [(p) => p * p, Math.sqrt],
  cubic: [(p) => p ** 3, Math.cbrt],
  cie: [
    (p) => (p * 100 <= 8 ? (p * 100) / 903.3 : ((p * 100 + 16) / 116) ** 3),
    (o) => (o <= 8 / 903.3 ? o * 903.3 : 116 * Math.cbrt(o) - 16) / 100,
  ],
  log: [
    (p) => Math.expm1(LOG_K * p) / Math.expm1(LOG_K),
    (o) => Math.log1p(o * Math.expm1(LOG_K)) / LOG_K,
  ],
};

const EASE_LABELS = {
  linear: "Linear",
  ease_in: "Ease in",
  ease_out: "Ease out",
  ease_in_out: "Ease in-out",
  sine: "Sine",
  step: "Hold, then jump",
};
const CURVE_LABELS = {
  linear: "Linear",
  square: "Square law",
  cubic: "Cubic",
  cie: "CIE 1931 (perceptual)",
  log: "Logarithmic",
};
const MODE_LABELS = { none: "Unchanged", ct: "Color temperature", rgb: "RGB color" };

const ZOOMS = [
  [86400, "24 h"], [43200, "12 h"], [21600, "6 h"], [10800, "3 h"], [3600, "1 h"],
  [1800, "30 min"], [900, "15 min"], [300, "5 min"], [60, "1 min"],
];
const SNAPS = [[1, "1 s"], [5, "5 s"], [15, "15 s"], [60, "1 min"], [300, "5 min"], [900, "15 min"]];
const TICKS = [1, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];

const mod = (x, m) => ((x % m) + m) % m;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const pad = (n) => String(n).padStart(2, "0");
const fmt = (t, sec) => {
  t = Math.round(t);
  const hm = `${pad(Math.floor(t / 3600))}:${pad(Math.floor((t % 3600) / 60))}`;
  return sec ? `${hm}:${pad(t % 60)}` : hm;
};
const parseTime = (v) => v.split(":").reduce((acc, p, i) => acc + +p * [3600, 60, 1][i], 0);
const hex = (rgb) => "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const rgbCss = (c, a = 1) => `rgba(${c.map(Math.round).join(",")},${a})`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const options = (labels) =>
  Object.entries(labels).map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
const sortNodes = (nodes) => nodes.sort((a, b) => a.t - b.t);

// Same algorithm as homeassistant.util.color.color_temperature_to_rgb.
function kelvinToRgb(kelvin) {
  const t = clamp(kelvin, 1000, 40000) / 100;
  const c = (v) => clamp(v, 0, 255);
  const r = t <= 66 ? 255 : c(329.698727446 * (t - 60) ** -0.1332047592);
  const g = t <= 66
    ? c(99.4708025861 * Math.log(t) - 161.1195681661)
    : c(288.1221695283 * (t - 60) ** -0.0755148492);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : c(138.5177312231 * Math.log(t - 10) - 305.0447927307);
  return [r, g, b];
}

const nodeColor = (n) => (n.mode === "ct" ? kelvinToRgb(n.k) : n.mode === "rgb" ? n.rgb : null);

function segment(nodes, t) {
  if (nodes.length === 1) return [nodes[0], nodes[0], 0];
  for (let i = 0; i < nodes.length - 1; i++) {
    const a = nodes[i], b = nodes[i + 1];
    if (a.t <= t && t < b.t) return [a, b, (t - a.t) / (b.t - a.t)];
  }
  const a = nodes[nodes.length - 1], b = nodes[0];
  return [a, b, mod(t - a.t, DAY) / (mod(b.t - a.t, DAY) || DAY)];
}

const warmKelvin = (brightness) => Math.round(1200 + 15 * brightness);

function sample(nodes, t, fadeToWarm = false, temperatureRange = [1000, 12000]) {
  const [a, b, x] = segment(nodes, t);
  const e = (EASE[a.ease] || EASE.linear)(x);
  const [curve, inv] = CURVE[a.curve] || CURVE.linear;
  const p0 = inv(a.b / 100), p1 = inv(b.b / 100);
  const bri = curve(p0 + (p1 - p0) * e) * 100;
  if (fadeToWarm) return { bri, rgb: kelvinToRgb(clamp(warmKelvin(bri), ...temperatureRange)) };
  if (!nodeColor(a)) return { bri, rgb: null };
  const end = nodeColor(b) ? b : a;
  if (a.mode === "ct" && end.mode === "ct") {
    const m0 = 1e6 / a.k, m1 = 1e6 / end.k;
    return { bri, rgb: kelvinToRgb(clamp(1e6 / (m0 + (m1 - m0) * e), ...temperatureRange)) };
  }
  const c0 = nodeColor(a), c1 = nodeColor(end);
  return { bri, rgb: c0.map((v, i) => v + (c1[i] - v) * e) };
}

function nowSeconds(timeZone) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone, hour: "numeric", minute: "numeric", second: "numeric", hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (type) => +parts.find((p) => p.type === type).value;
  return get("hour") * 3600 + get("minute") * 60 + get("second");
}

const STYLE = `
  :host {
    display: block; height: 100%; overflow-y: auto;
    background: var(--primary-background-color); color: var(--primary-text-color);
    font-family: var(--ha-font-family-body, Roboto, sans-serif);
  }
  .toolbar {
    position: sticky; top: 0; z-index: 2; display: flex; align-items: center; gap: 8px;
    height: var(--header-height, 56px); padding: 0 12px; box-sizing: border-box;
    background: var(--app-header-background-color); color: var(--app-header-text-color, white);
    border-bottom: var(--app-header-border-bottom, none);
  }
  .title { flex: 1; font-size: 20px; }
  .status { font-size: 14px; opacity: 0.8; }
  .toolbar .history { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; width: 36px; height: 36px; padding: 0; border: none; color: inherit; }
  .history:disabled { opacity: 0.35; cursor: default; }
  .controls { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; padding: 12px 16px; }
  .controls label { display: flex; gap: 8px; align-items: center; }
  .controls .pan { flex: 1; min-width: 200px; }
  .controls .pan input { flex: 1; }
  .tz { color: var(--secondary-text-color); font-size: 13px; }
  .rows { display: flex; flex-direction: column; gap: 12px; padding: 0 16px 16px; }
  ha-card { display: block; background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 12px); }
  summary { display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; list-style: none; }
  summary::-webkit-details-marker { display: none; }
  summary ha-icon { transition: transform 0.2s; color: var(--secondary-text-color); }
  details[open] summary ha-icon { transform: rotate(90deg); }
  .name { font-weight: 500; }
  .meta { flex: 1; color: var(--secondary-text-color); font-size: 13px; }
  .mini { width: 30%; max-width: 240px; height: 12px; border-radius: 6px; border: 1px solid var(--divider-color); }
  .body { padding: 0 16px 16px; }
  svg.graph { display: block; width: 100%; height: 200px; touch-action: none; user-select: none; cursor: crosshair; }
  .plot { fill: transparent; stroke: var(--divider-color); }
  .grid { stroke: var(--divider-color); opacity: 0.6; }
  .label { fill: var(--secondary-text-color); font-size: 11px; }
  .curve { fill: none; stroke: var(--primary-color); stroke-width: 2; }
  .now { stroke: var(--error-color); stroke-dasharray: 4 3; }
  .node { stroke: var(--primary-color); stroke-width: 2; cursor: grab; }
  .node.selected { stroke: var(--primary-text-color); stroke-width: 3; }
  .hint { font-size: 12px; color: var(--secondary-text-color); margin: 4px 0 12px; }
  .editor, .row-actions { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
  .editor:empty { display: none; }
  .editor label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--secondary-text-color); }
  .row-actions { margin-top: 12px; align-items: center; }
  input, select, button {
    font: inherit; color: var(--primary-text-color); box-sizing: border-box;
    background: var(--input-fill-color, var(--secondary-background-color));
    border: 1px solid var(--divider-color); border-radius: 4px; padding: 6px 8px;
  }
  input[type="range"] { padding: 0; accent-color: var(--primary-color); }
  input[type="color"] { padding: 0; width: 48px; height: 34px; }
  input[type="checkbox"] { accent-color: var(--primary-color); }
  button { cursor: pointer; background: none; color: var(--primary-color); border-color: var(--primary-color); }
`;

class LightTimelinePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = { start: 0, span: DAY };
    this._snap = 60;
    this._rows = {};
    this._selected = null;
    this._drag = null;
    this._history = [];
    this._historyIndex = -1;
  }

  set hass(hass) {
    const previous = this._hass;
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._init();
    else {
      for (const row of Object.values(this._rows)) {
        const before = previous.states[row.eid]?.attributes || {};
        const after = hass.states[row.eid]?.attributes || {};
        if (before.min_color_temp_kelvin !== after.min_color_temp_kelvin ||
            before.max_color_temp_kelvin !== after.max_color_temp_kelvin) {
          this._renderEditor(row);
          this._drawGraph(row);
          this._renderSummary(row);
        }
      }
    }
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
  }

  connectedCallback() {
    this._timer = setInterval(() => this._drawAll(), 30000);
    this._resize = new ResizeObserver(() => this._drawAll());
    this._resize.observe(this);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._resize.disconnect();
  }

  async _init() {
    const root = this.shadowRoot;
    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="title">Light Timeline</div>
        <span class="status"></span>
        <button class="history undo" type="button" aria-label="Undo" title="Undo" disabled><ha-icon icon="mdi:undo" aria-hidden="true"></ha-icon></button>
        <button class="history redo" type="button" aria-label="Redo" title="Redo" disabled><ha-icon icon="mdi:redo" aria-hidden="true"></ha-icon></button>
      </div>
      <div class="controls">
        <label>Zoom <select class="zoom">${ZOOMS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
        <label class="pan">Position <input class="pan-input" type="range" min="0" step="1"></label>
        <label>Snap <select class="snap">${SNAPS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
        <span class="tz"></span>
      </div>
      <div class="rows"></div>`;
    this._menu = root.querySelector("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    this._status = root.querySelector(".status");
    this._undo = root.querySelector(".undo");
    this._redo = root.querySelector(".redo");
    this._undo.addEventListener("click", () => this._restoreHistory(-1));
    this._redo.addEventListener("click", () => this._restoreHistory(1));
    this._zoom = root.querySelector(".zoom");
    this._pan = root.querySelector(".pan-input");
    const snap = root.querySelector(".snap");
    snap.value = this._snap;
    snap.addEventListener("change", () => (this._snap = +snap.value));
    this._zoom.addEventListener("change", () => {
      const { start, span } = this._view;
      const next = +this._zoom.value;
      this._setView(start + span / 2 - next / 2, next);
    });
    this._pan.addEventListener("input", () => this._setView(+this._pan.value, this._view.span));
    root.querySelector(".tz").textContent = `Times in ${this._hass.config.time_zone}`;

    try {
      const data = await this._hass.callWS({ type: "light_timeline/get" });
      this._schedules = data.schedules;
      this._buildRows(root.querySelector(".rows"), data.lights);
      this._recordHistory();
    } catch (err) {
      this._status.textContent = `Failed to load: ${err.message}`;
      return;
    }
    this._setView(0, DAY);
  }

  _name(entityId) {
    return this._hass.states[entityId]?.attributes.friendly_name || entityId;
  }

  _temperatureRange(row) {
    const attrs = this._hass.states[row.eid]?.attributes || {};
    return [attrs.min_color_temp_kelvin ?? 1000, attrs.max_color_temp_kelvin ?? 12000];
  }

  _buildRows(container, lights) {
    lights = [...lights].sort((a, b) => this._name(a).localeCompare(this._name(b)));
    if (!lights.length) container.textContent = "No lights found.";
    lights.forEach((eid, idx) => {
      this._schedules[eid] ??= { enabled: true, nodes: [] };
      this._schedules[eid].fade_to_warm ??= false;
      const others = lights.filter((o) => o !== eid)
        .map((o) => `<option value="${esc(o)}">${esc(this._name(o))}</option>`).join("");
      const card = document.createElement("ha-card");
      card.innerHTML = `<details name="light-timeline">
          <summary><ha-icon icon="mdi:chevron-right"></ha-icon><span class="name"></span><span class="meta"></span><span class="mini"></span></summary>
          <div class="body">
            <svg class="graph"></svg>
            <div class="hint">Click to add a node, drag to move, double-click to delete. Ctrl + scroll to zoom, Shift + scroll to pan.</div>
            <div class="editor"></div>
            <div class="row-actions">
              <label><input type="checkbox" class="enabled"> Enabled</label>
              <label title="1200 K at 0% brightness, 2700 K at 100%; overrides node colors"><input type="checkbox" class="fade-to-warm"> Fade to warm</label>
              <select class="copy"><option value="">Copy timeline to…</option><option value="*">All other lights</option>${others}</select>
              <button class="clear">Clear</button>
            </div>
          </div>
        </details>`;
      const $ = (sel) => card.querySelector(sel);
      const row = {
        eid, idx, details: $("details"), svg: $("svg"), editor: $(".editor"),
        meta: $(".meta"), mini: $(".mini"), enabled: $(".enabled"), fadeToWarm: $(".fade-to-warm"),
      };
      $(".name").textContent = this._name(eid);
      this._rows[eid] = row;
      this._bindRow(row, $(".copy"), $(".clear"), lights);
      container.append(card);
      this._renderSummary(row);
    });
  }

  _bindRow(row, copy, clear, lights) {
    const sched = this._schedules[row.eid];
    const svg = row.svg;
    row.details.addEventListener("toggle", () => {
      if (!row.details.open) {
        const focused = this.shadowRoot.activeElement;
        if (focused && row.details.contains(focused)) focused.blur();
        if (this._drag?.row === row) this._onUp();
        if (this._saveTimer) {
          clearTimeout(this._saveTimer);
          this._saveTimer = null;
          this._save();
        }
      }
      this._drawGraph(row);
    });
    svg.addEventListener("pointerdown", (ev) => this._onDown(row, ev));
    svg.addEventListener("pointermove", (ev) => this._onMove(ev));
    svg.addEventListener("pointerup", () => this._onUp());
    svg.addEventListener("pointercancel", () => this._onUp());
    svg.addEventListener("dblclick", (ev) => {
      const i = ev.target.dataset?.i;
      if (i !== undefined) this._deleteNode(row, sched.nodes[+i]);
    });
    svg.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey && !ev.shiftKey) return;
      ev.preventDefault();
      const { start, span } = this._view;
      if (ev.ctrlKey) {
        const t = this._point(row, ev).t;
        const next = clamp(span * (ev.deltaY > 0 ? 1.25 : 0.8), 60, DAY);
        this._setView(t - ((t - start) * next) / span, next);
      } else {
        this._setView(start + ((ev.deltaX || ev.deltaY) / 500) * span, span);
      }
    }, { passive: false });
    row.enabled.addEventListener("change", () => {
      sched.enabled = row.enabled.checked;
      this._changed(row);
    });
    row.fadeToWarm.addEventListener("change", () => {
      sched.fade_to_warm = row.fadeToWarm.checked;
      this._renderEditor(row);
      this._drawGraph(row);
      this._changed(row);
    });
    clear.addEventListener("click", () => {
      if (!sched.nodes.length || !confirm(`Remove all nodes from ${this._name(row.eid)}?`)) return;
      sched.nodes = [];
      this._select(null, null);
      this._drawGraph(row);
      this._changed(row);
    });
    copy.addEventListener("change", () => {
      const value = copy.value;
      copy.value = "";
      const targets = value === "*" ? lights.filter((o) => o !== row.eid) : [value];
      if (!confirm(`Replace the timeline of ${targets.length} light(s) with this one?`)) return;
      for (const eid of targets) {
        this._schedules[eid].nodes = structuredClone(sched.nodes);
        this._schedules[eid].fade_to_warm = sched.fade_to_warm || false;
        this._renderEditor(this._rows[eid]);
        this._drawGraph(this._rows[eid]);
        this._changed(this._rows[eid], false);
      }
      this._recordHistory();
    });
  }

  _setView(start, span) {
    span = clamp(span, 60, DAY);
    start = clamp(start, 0, DAY - span);
    this._view = { start, span };
    this._pan.max = DAY - span;
    this._pan.value = start;
    this._pan.disabled = span === DAY;
    if (ZOOMS.some(([v]) => v === span)) this._zoom.value = span;
    this._drawAll();
  }

  _drawAll() {
    Object.values(this._rows).forEach((row) => this._drawGraph(row));
  }

  _point(row, ev) {
    const rect = row.svg.getBoundingClientRect();
    const { L, T, pw, ph } = row.geo;
    const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
    return {
      px, py,
      t: this._view.start + ((px - L) / pw) * this._view.span,
      b: 100 - ((py - T) / ph) * 100,
      inside: px >= L && px <= L + pw && py >= T - 8 && py <= T + ph + 8,
    };
  }

  _snapT(t) {
    return clamp(Math.round(t / this._snap) * this._snap, 0, DAY - 1);
  }

  _drawGraph(row) {
    if (!row?.details.open) return;
    const W = row.svg.clientWidth;
    if (!W) return;
    const H = 200, L = 40, R = 12, T = 12, B = 24;
    const pw = W - L - R, ph = H - T - B;
    const { start, span } = this._view, end = start + span;
    const nodes = this._schedules[row.eid].nodes;
    const fadeToWarm = this._schedules[row.eid].fade_to_warm;
    const temperatureRange = this._temperatureRange(row);
    const selected = this._selected?.row === row ? this._selected.node : null;
    const x = (t) => (L + ((t - start) / span) * pw).toFixed(1);
    const y = (b) => (T + (1 - b / 100) * ph).toFixed(1);
    row.geo = { L, T, pw, ph };
    const out = [];

    for (const b of [0, 25, 50, 75, 100]) {
      out.push(`<line class="grid" x1="${L}" x2="${L + pw}" y1="${y(b)}" y2="${y(b)}"/>`,
        `<text class="label" x="${L - 6}" y="${+y(b) + 4}" text-anchor="end">${b}%</text>`);
    }
    const step = TICKS.find((s) => span / s <= pw / 70) || 21600;
    for (let t = Math.ceil(start / step) * step; t <= end; t += step) {
      out.push(`<line class="grid" x1="${x(t)}" x2="${x(t)}" y1="${T}" y2="${T + ph}"/>`,
        `<text class="label" x="${x(t)}" y="${H - 6}" text-anchor="middle">${fmt(t, step < 60)}</text>`);
    }
    out.push(`<rect class="plot" x="${L}" y="${T}" width="${pw}" height="${ph}"/>`);

    if (nodes.length) {
      const stops = [];
      for (let i = 0; i <= 48; i++) {
        const s = sample(nodes, mod(start + (span * i) / 48, DAY), fadeToWarm, temperatureRange);
        const opacity = (0.15 + 0.6 * s.bri / 100).toFixed(2);
        const color = s.rgb ? rgbCss(s.rgb) : "var(--primary-color)";
        stops.push(`<stop offset="${i / 48}" style="stop-color:${color};stop-opacity:${opacity}"/>`);
      }
      const n = Math.ceil(pw / 3);
      const ts = Array.from({ length: n + 1 }, (_, i) => start + (span * i) / n);
      for (const nd of nodes) if (nd.t > start && nd.t < end) ts.push(nd.t - 0.001, nd.t);
      ts.sort((a, b) => a - b);
      const pts = ts.map((t) => `${x(t)},${y(sample(nodes, mod(t, DAY)).bri)}`);
      out.push(
        `<defs><linearGradient id="grad${row.idx}" gradientUnits="userSpaceOnUse" x1="${L}" x2="${L + pw}" y1="0" y2="0">${stops.join("")}</linearGradient></defs>`,
        `<path fill="url(#grad${row.idx})" d="M${L},${y(0)} L${pts.join(" L")} L${L + pw},${y(0)} Z"/>`,
        `<polyline class="curve" points="${pts.join(" ")}"/>`,
      );
    }

    const now = nowSeconds(this._hass.config.time_zone);
    if (now >= start && now <= end) {
      out.push(`<line class="now" x1="${x(now)}" x2="${x(now)}" y1="${T}" y2="${T + ph}"/>`);
    }

    nodes.forEach((nd, i) => {
      if (nd.t < start || nd.t > end) return;
      const c = fadeToWarm || nd.mode === "ct"
        ? kelvinToRgb(clamp(fadeToWarm ? warmKelvin(nd.b) : nd.k, ...temperatureRange))
        : nodeColor(nd);
      out.push(`<circle class="node${nd === selected ? " selected" : ""}" data-i="${i}" cx="${x(nd.t)}" cy="${y(nd.b)}" r="7" style="fill:${c ? rgbCss(c) : "var(--card-background-color)"}"/>`);
    });
    row.svg.innerHTML = out.join("");
  }

  _renderSummary(row) {
    const sched = this._schedules[row.eid];
    const count = sched.nodes.length;
    row.meta.textContent = `${count} node${count === 1 ? "" : "s"}${sched.enabled ? "" : " · disabled"}`;
    row.enabled.checked = sched.enabled;
    row.fadeToWarm.checked = sched.fade_to_warm || false;
    const stops = [];
    for (let i = 0; count && i <= 48; i++) {
      const s = sample(sched.nodes, (DAY * i) / 48, sched.fade_to_warm, this._temperatureRange(row));
      const pct = Math.round(15 + 0.85 * s.bri);
      stops.push(s.rgb
        ? rgbCss(s.rgb, pct / 100)
        : `color-mix(in srgb, var(--primary-color) ${pct}%, transparent)`);
    }
    row.mini.style.background = count ? `linear-gradient(to right, ${stops.join(",")})` : "";
  }

  _newNode(nodes, t, b) {
    const base = nodes.length
      ? segment(nodes, t)[0]
      : { mode: "none", k: 2700, rgb: [255, 255, 255], ease: "linear", curve: "linear" };
    return { t, b, mode: base.mode, k: base.k, rgb: [...base.rgb], ease: base.ease, curve: base.curve };
  }

  _onDown(row, ev) {
    if (ev.button !== 0 || !row.geo) return;
    const nodes = this._schedules[row.eid].nodes;
    const p = this._point(row, ev);
    const i = ev.target.dataset?.i;
    let node;
    let created = false;
    if (i !== undefined) {
      node = nodes[+i];
    } else {
      if (!p.inside) return;
      node = this._newNode(nodes, this._snapT(p.t), clamp(Math.round(p.b), 0, 100));
      nodes.push(node);
      sortNodes(nodes);
      created = true;
    }
    this._drag = { row, node, created, offT: node.t - p.t, offB: node.b - p.b };
    row.svg.setPointerCapture(ev.pointerId);
    ev.preventDefault();
    this._select(row, node);
  }

  _onMove(ev) {
    const d = this._drag;
    if (!d) return;
    const p = this._point(d.row, ev);
    d.node.t = this._snapT(p.t + d.offT);
    d.node.b = clamp(Math.round(p.b + d.offB), 0, 100);
    d.moved = true;
    sortNodes(this._schedules[d.row.eid].nodes);
    this._drawGraph(d.row);
    this._syncEditor(d.row);
  }

  _onUp() {
    const d = this._drag;
    this._drag = null;
    if (d && (d.moved || d.created)) this._changed(d.row);
  }

  _select(row, node) {
    const prev = this._selected?.row;
    this._selected = row ? { row, node } : null;
    if (prev && prev !== row) {
      this._renderEditor(prev);
      this._drawGraph(prev);
    }
    if (row) {
      this._renderEditor(row);
      this._drawGraph(row);
    }
  }

  _deleteNode(row, node) {
    const nodes = this._schedules[row.eid].nodes;
    nodes.splice(nodes.indexOf(node), 1);
    this._select(null, null);
    this._renderEditor(row);
    this._drawGraph(row);
    this._changed(row);
  }

  _renderEditor(row) {
    const node = this._selected?.row === row ? this._selected.node : null;
    if (!node) {
      row.editor.innerHTML = "";
      return;
    }
    const fadeToWarm = this._schedules[row.eid].fade_to_warm;
    const mode = fadeToWarm ? "ct" : node.mode;
    const [kMin, kMax] = this._temperatureRange(row);
    const kGradient = `linear-gradient(to right, ${rgbCss(kelvinToRgb(kMin))}, ${rgbCss(kelvinToRgb(kMax))})`;
    row.editor.innerHTML = `
      <label>Time<input name="t" type="time" step="1"></label>
      <label>Brightness (%)<input name="b" type="number" min="0" max="100" step="1"></label>
      <label>Color<select name="mode">${options(MODE_LABELS)}</select></label>
      ${mode === "ct" ? `<label>Color temperature (<span class="kval"></span> K)<input name="k" type="range" min="${kMin}" max="${kMax}" step="1" style="background:${kGradient}"></label>` : ""}
      ${mode === "rgb" ? `<label>RGB color<input name="rgb" type="color"></label>` : ""}
      <label>Easing to next node<select name="ease">${options(EASE_LABELS)}</select></label>
      <label>Dimmer curve<select name="curve">${options(CURVE_LABELS)}</select></label>
      <button class="delete">Delete node</button>`;
    this._syncEditor(row);
    for (const el of row.editor.querySelectorAll("input, select")) {
      if (el.type === "range" || el.name === "b") {
        el.addEventListener("input", () => this._edit(row, node, el, false));
        el.addEventListener("change", () => this._changed(row));
      } else {
        el.addEventListener("change", () => this._edit(row, node, el));
      }
    }
    row.editor.querySelector(".delete").addEventListener("click", () => this._deleteNode(row, node));
  }

  _syncEditor(row) {
    const node = this._selected?.row === row ? this._selected.node : null;
    if (!node) return;
    const fadeToWarm = this._schedules[row.eid].fade_to_warm;
    const kelvin = clamp(fadeToWarm ? warmKelvin(node.b) : node.k, ...this._temperatureRange(row));
    const set = (name, value) => {
      const el = row.editor.querySelector(`[name="${name}"]`);
      if (el && el !== this.shadowRoot.activeElement) el.value = value;
    };
    set("t", fmt(node.t, true));
    set("b", node.b);
    set("mode", fadeToWarm ? "ct" : node.mode);
    set("k", kelvin);
    set("rgb", hex(node.rgb));
    set("ease", node.ease);
    set("curve", node.curve);
    for (const name of ["mode", "k", "rgb"]) {
      const el = row.editor.querySelector(`[name="${name}"]`);
      if (el) el.disabled = fadeToWarm || false;
    }
    const kval = row.editor.querySelector(".kval");
    if (kval) kval.textContent = kelvin;
  }

  _edit(row, node, el, record = true) {
    const v = el.value;
    switch (el.name) {
      case "t":
        if (!v) return;
        node.t = clamp(parseTime(v), 0, DAY - 1);
        sortNodes(this._schedules[row.eid].nodes);
        break;
      case "b":
        node.b = clamp(Math.round(+v || 0), 0, 100);
        break;
      case "mode":
        node.mode = v;
        this._renderEditor(row);
        break;
      case "k":
        node.k = +v;
        break;
      case "rgb":
        node.rgb = hexToRgb(v);
        break;
      default:
        node[el.name] = v;
    }
    this._syncEditor(row);
    this._drawGraph(row);
    this._changed(row, record);
  }

  _recordHistory() {
    const snapshot = structuredClone(this._schedules);
    if (JSON.stringify(snapshot) === JSON.stringify(this._history[this._historyIndex])) return;
    this._history.splice(this._historyIndex + 1);
    this._history.push(snapshot);
    if (this._history.length > 101) this._history.shift();
    this._historyIndex = this._history.length - 1;
    this._updateHistoryButtons();
  }

  _updateHistoryButtons() {
    this._undo.disabled = this._historyIndex <= 0;
    this._redo.disabled = this._historyIndex >= this._history.length - 1;
  }

  _restoreHistory(direction) {
    const index = this._historyIndex + direction;
    if (index < 0 || index >= this._history.length) return;
    this._historyIndex = index;
    this._selected = null;
    this._drag = null;
    const snapshot = structuredClone(this._history[index]);
    for (const [eid, schedule] of Object.entries(snapshot)) {
      Object.assign(this._schedules[eid], schedule);
    }
    for (const row of Object.values(this._rows)) {
      this._renderEditor(row);
      this._renderSummary(row);
      this._drawGraph(row);
    }
    this._updateHistoryButtons();
    this._scheduleSave();
  }

  _changed(row, record = true) {
    this._renderSummary(row);
    if (record) this._recordHistory();
    this._scheduleSave();
  }

  _scheduleSave() {
    this._status.textContent = "Saving…";
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null;
      this._save();
    }, 800);
  }

  async _save() {
    try {
      await this._hass.callWS({ type: "light_timeline/save", schedules: this._schedules });
      this._status.textContent = "Saved";
    } catch (err) {
      this._status.textContent = `Save failed: ${err.message}`;
    }
  }
}

customElements.define("light-timeline-panel", LightTimelinePanel);
