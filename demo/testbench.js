(() => {
  const storageKey = "light-timeline-testbench-v1";
  const node = (time, brightness, properties = {}) => ({
    t: time, b: brightness, mode: "none", k: 2700, rgb: [255, 255, 255],
    ease: "sine", curve: "cie", ...properties,
  });
  const lights = {
    "light.bedroom": { friendly_name: "Bedroom", supported_color_modes: ["color_temp"], min_color_temp_kelvin: 2000, max_color_temp_kelvin: 6500 },
    "light.kitchen": { friendly_name: "Kitchen", supported_color_modes: ["brightness"] },
    "light.living_room": { friendly_name: "Living room", supported_color_modes: ["rgb", "color_temp"], min_color_temp_kelvin: 2200, max_color_temp_kelvin: 6500 },
    "light.studio": { friendly_name: "Studio accents", supported_color_modes: ["rgb"] },
  };
  const defaults = {
    "light.bedroom": { enabled: true, nodes: [
      node(0, 0, { mode: "ct", k: 2200 }),
      node(21600, 0, { mode: "ct", k: 2200 }),
      node(27000, 85, { mode: "ct", k: 5000 }),
      node(64800, 60, { mode: "ct", k: 3000 }),
      node(82800, 0, { mode: "ct", k: 2200 }),
    ] },
    "light.kitchen": { enabled: true, nodes: [
      node(0, 0, { ease: "step" }),
      node(25200, 100, { ease: "step" }),
      node(32400, 0, { ease: "step" }),
      node(64800, 80), node(79200, 0),
    ] },
    "light.living_room": { enabled: true, nodes: [
      node(0, 5, { mode: "ct", k: 2200 }),
      node(28800, 65, { mode: "ct", k: 4500 }),
      node(61200, 90, { mode: "ct", k: 3000 }),
      node(75600, 40, { mode: "rgb", rgb: [255, 110, 65] }),
      node(84600, 5, { mode: "rgb", rgb: [235, 45, 90] }),
    ] },
    "light.studio": { enabled: true, nodes: [
      node(0, 10, { mode: "rgb", rgb: [30, 160, 255] }),
      node(43200, 75, { mode: "rgb", rgb: [60, 225, 160] }),
      node(64800, 95, { mode: "rgb", rgb: [255, 70, 100], ease: "ease_in_out" }),
      node(64830, 20, { mode: "rgb", rgb: [255, 200, 50], ease: "ease_out" }),
      node(64860, 85, { mode: "rgb", rgb: [45, 150, 255] }),
      node(82800, 10, { mode: "rgb", rgb: [30, 160, 255] }),
    ] },
  };
  const storageStatus = document.querySelector("#storage-status");
  let schedules = structuredClone(defaults);
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (stored) {
      if (!Object.keys(lights).every((entityId) =>
        Array.isArray(stored[entityId]?.nodes) && typeof stored[entityId]?.enabled === "boolean"
      )) throw new Error("Invalid demo data");
      schedules = stored;
    }
  } catch {
    storageStatus.textContent = "Local saves unavailable or invalid; using sample timelines.";
  }

  class DemoIcon extends HTMLElement {
    static observedAttributes = ["icon"];

    constructor() {
      super();
      this.attachShadow({ mode: "open" });
    }

    attributeChangedCallback() {
      const paths = {
        "mdi:chevron-right": "M9.29 6.71L13.88 11.3L9.29 15.89L10.71 17.3L16.71 11.3L10.71 5.3Z",
        "mdi:undo": "M12.5 8C9.85 8 7.45 8.99 5.6 10.6L2 7V16H11L7.02 12.02C8.54 10.76 10.44 10 12.5 10C16.04 10 19.06 12.31 20.11 15.5L22.48 14.72C21.08 10.72 17.14 8 12.5 8Z",
        "mdi:redo": "M18.4 10.6C16.55 8.99 14.15 8 11.5 8C6.86 8 2.92 10.72 1.52 14.72L3.89 15.5C4.94 12.31 7.96 10 11.5 10C13.56 10 15.46 10.76 16.98 12.02L13 16H22V7Z",
        "mdi:file-restore": "M14 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V8L14 2M13 3.5L18.5 9H13V3.5M10.5 12C13 12 15 14 15 16.5H13C13 15.12 11.88 14 10.5 14H10V16L7 13L10 10V12H10.5Z",
      };
      this.shadowRoot.innerHTML = `<style>:host{display:inline-grid;place-items:center;width:24px;height:24px}svg{width:24px;height:24px;fill:currentColor}</style><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[this.getAttribute("icon")] || ""}"></path></svg>`;
    }
  }
  customElements.define("ha-icon", DemoIcon);

  const panel = document.querySelector("light-timeline-panel");
  panel.narrow = matchMedia("(max-width: 600px)").matches;
  panel.hass = {
    config: { time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" },
    states: Object.fromEntries(Object.entries(lights).map(([entityId, attributes]) =>
      [entityId, { entity_id: entityId, state: "on", attributes }]
    )),
    async callWS(message) {
      if (message.type === "light_timeline/get") {
        return { lights: Object.keys(lights), schedules: structuredClone(schedules) };
      }
      if (message.type === "light_timeline/save") {
        const snapshot = structuredClone(message.schedules);
        localStorage.setItem(storageKey, JSON.stringify(snapshot));
        schedules = snapshot;
        storageStatus.textContent = "";
        return null;
      }
      throw new Error(`Unsupported demo command: ${message.type}`);
    },
  };
  Promise.resolve().then(() => {
    panel.shadowRoot.querySelector("details").open = true;
  });
  document.querySelector("#theme").addEventListener("change", (event) => {
    document.documentElement.dataset.theme = event.target.checked ? "dark" : "light";
  });
  document.querySelector("#reset").addEventListener("click", () => {
    if (!confirm("Reset all demo timelines to their sample values?")) return;
    try {
      localStorage.removeItem(storageKey);
      location.reload();
    } catch {
      storageStatus.textContent = "Cannot reset local storage in this browser.";
    }
  });
})();