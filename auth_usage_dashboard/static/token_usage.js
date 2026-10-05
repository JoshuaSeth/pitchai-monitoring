(function () {
  "use strict";

  // Fleet token ledger: stacked hourly columns per dimension (provider, model,
  // project). Every dimension panel and every series inside it can be switched
  // off; preferences stay in this browser only.

  const STORAGE_KEY = "codexusage.tokenLayers.v1";
  const REFRESH_MS = 60_000;
  const DIMENSIONS = [
    { key: "provider", label: "By provider", detail: "Engine runtime family" },
    { key: "model", label: "By model", detail: "Model reported by the runtime" },
    { key: "project", label: "By project", detail: "Engine lane project" },
  ];
  const RANGES = [
    { key: "24h", label: "24 hours" },
    { key: "7d", label: "7 days" },
    { key: "30d", label: "30 days" },
  ];
  // Validated categorical order (adjacent CVD/normal-vision pass on white);
  // "Other" is a neutral so it never impersonates a series.
  const SLOT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"];
  const OTHER_COLOR = "#9b9a94";

  const prefs = loadPrefs();
  const view = { payload: null, loading: false, lastLoaded: 0, error: null };

  function loadPrefs() {
    const defaults = { enabled: true, range: "7d", metric: "total", dimensions: { provider: true, model: true, project: true }, hidden: {} };
    try {
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (!stored || typeof stored !== "object") return defaults;
      return {
        enabled: stored.enabled !== false,
        range: RANGES.some((item) => item.key === stored.range) ? stored.range : defaults.range,
        metric: typeof stored.metric === "string" ? stored.metric : defaults.metric,
        dimensions: { ...defaults.dimensions, ...(stored.dimensions || {}) },
        hidden: stored.hidden && typeof stored.hidden === "object" ? stored.hidden : {},
      };
    } catch (error) {
      return defaults;
    }
  }

  function savePrefs() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch (error) {
      // Storage can be unavailable (private mode); preferences then last one page view.
    }
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }

  function svgElement(tag, className, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (className) node.setAttribute("class", className);
    for (const [name, value] of Object.entries(attributes || {})) node.setAttribute(name, String(value));
    return node;
  }

  function finite(value) {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function compact(value) {
    const parsed = finite(value);
    if (parsed === null) return "-";
    return new Intl.NumberFormat(undefined, {
      notation: Math.abs(parsed) >= 10_000 ? "compact" : "standard",
      maximumFractionDigits: Math.abs(parsed) >= 10_000 ? 1 : 0,
    }).format(parsed);
  }

  function percent(part, whole) {
    if (!whole) return "-";
    const value = part / whole * 100;
    return `${value < 0.1 && value > 0 ? "<0.1" : value.toFixed(value >= 10 ? 0 : 1)}%`;
  }

  function niceMaximum(value) {
    const maximum = Math.max(1, Number(value) || 0);
    const magnitude = 10 ** Math.floor(Math.log10(maximum));
    const normalized = maximum / magnitude;
    const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((candidate) => normalized <= candidate) || 10;
    return step * magnitude;
  }

  function zoneParts(iso) {
    const date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return null;
    const parts = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", hourCycle: "h23", timeZone: currentZone() }).formatToParts(date);
    const read = (type) => (parts.find((part) => part.type === type) || {}).value;
    return { day: `${read("month")} ${read("day")}`, hour: Number(read("hour")) % 24 };
  }

  // Calendar-aware ticks: hours on the 24h view, day changes on 7d, every few days on 30d.
  function tickLabel(buckets, index, bucketSeconds, compactLayout) {
    const here = zoneParts(buckets[index]);
    if (!here) return null;
    if (bucketSeconds < 10_800) {
      const every = compactLayout ? 12 : 6;
      if (here.hour % every !== 0) return null;
      return here.hour === 0 ? here.day : `${String(here.hour).padStart(2, "0")}:00`;
    }
    if (bucketSeconds < 86_400) {
      const previous = index > 0 ? zoneParts(buckets[index - 1]) : null;
      if (previous && previous.day === here.day) return null;
      if (!previous && here.hour !== 0) return null;
      const dayNumber = Math.floor(new Date(buckets[index]).getTime() / 86_400_000);
      return compactLayout && dayNumber % 2 ? null : here.day;
    }
    const every = compactLayout ? 10 : 5;
    return (buckets.length - 1 - index) % every === 0 ? here.day : null;
  }

  function bucketLabel(iso, bucketSeconds, withTime) {
    const date = new Date(iso);
    if (!Number.isFinite(date.getTime())) return "-";
    const options = { month: "short", day: "numeric", timeZone: currentZone() };
    if (withTime && bucketSeconds < 86400) {
      options.hour = "2-digit";
      options.minute = "2-digit";
      options.hour12 = false;
    }
    return new Intl.DateTimeFormat(undefined, options).format(date);
  }

  function currentZone() {
    const active = document.querySelector(".zone-option.is-active[data-zone]");
    return active && active.dataset.zone === "local" ? undefined : "UTC";
  }

  function ageText(iso) {
    const date = new Date(iso || "");
    if (!Number.isFinite(date.getTime())) return "never";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  function hiddenSet(dimension) {
    const values = prefs.hidden[dimension];
    return new Set(Array.isArray(values) ? values : []);
  }

  function setHidden(dimension, key, hidden) {
    const values = hiddenSet(dimension);
    if (hidden) values.add(key);
    else values.delete(key);
    prefs.hidden[dimension] = [...values];
    savePrefs();
  }

  function seriesColor(series, index) {
    if (series.other) return OTHER_COLOR;
    const slot = finite(series.color_slot);
    const position = slot !== null && slot >= 0 && slot < SLOT_COLORS.length ? slot : index;
    return SLOT_COLORS[position % SLOT_COLORS.length];
  }

  function metricPoints(series) {
    const points = series.points && typeof series.points === "object" ? series.points[prefs.metric] : null;
    return Array.isArray(points) ? points.map((value) => Math.max(0, finite(value) || 0)) : [];
  }

  function metricTotal(series) {
    const totals = series.totals || {};
    const value = finite(totals[prefs.metric]);
    return value === null ? metricPoints(series).reduce((sum, item) => sum + item, 0) : value;
  }

  function renderControls(payload) {
    const metrics = Array.isArray(payload && payload.metrics) && payload.metrics.length
      ? payload.metrics
      : [{ key: "total", label: "All tokens" }];
    if (!metrics.some((item) => item.key === prefs.metric)) prefs.metric = metrics[0].key;

    const rangeGroup = element("div", "token-segment");
    rangeGroup.setAttribute("role", "group");
    rangeGroup.setAttribute("aria-label", "Time range");
    for (const range of RANGES) {
      const button = element("button", `token-range-option${prefs.range === range.key ? " is-active" : ""}`, range.label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(prefs.range === range.key));
      button.addEventListener("click", () => {
        if (prefs.range === range.key) return;
        prefs.range = range.key;
        savePrefs();
        load(true);
      });
      rangeGroup.appendChild(button);
    }

    const metricSelect = element("select", "history-select token-metric");
    metricSelect.setAttribute("aria-label", "Token measure");
    for (const metric of metrics) {
      const option = element("option", "", metric.label);
      option.value = metric.key;
      metricSelect.appendChild(option);
    }
    metricSelect.value = prefs.metric;
    metricSelect.addEventListener("change", () => {
      prefs.metric = metricSelect.value;
      savePrefs();
      renderPanels();
    });

    const layerGroup = element("div", "token-layer-toggles");
    layerGroup.setAttribute("role", "group");
    layerGroup.setAttribute("aria-label", "Visible layers");
    for (const dimension of DIMENSIONS) {
      const label = element("label", "token-layer-toggle");
      const input = element("input");
      input.type = "checkbox";
      input.checked = prefs.dimensions[dimension.key] !== false;
      input.addEventListener("change", () => {
        prefs.dimensions[dimension.key] = input.checked;
        savePrefs();
        renderPanels();
      });
      label.append(input, element("span", "", dimension.label));
      layerGroup.appendChild(label);
    }
    byId("token-usage-controls").replaceChildren(rangeGroup, metricSelect, layerGroup);
  }

  function renderPanels() {
    const host = byId("token-usage-panels");
    const payload = view.payload;
    if (!payload) {
      host.replaceChildren(element("div", "chart-empty", view.error || "Reading the fleet token ledger..."));
      return;
    }
    if (payload.error && !payload.dimensions) {
      host.replaceChildren(element("div", "chart-empty", payload.error));
      return;
    }
    const panels = [];
    for (const dimension of DIMENSIONS) {
      if (prefs.dimensions[dimension.key] === false) continue;
      const data = (payload.dimensions || {})[dimension.key] || { series: [] };
      panels.push(renderPanel(dimension, data, payload));
    }
    if (!panels.length) panels.push(element("div", "chart-empty", "All layers are switched off. Enable a layer above to chart token usage."));
    host.replaceChildren(...panels);
    host.classList.toggle("is-refreshing", view.loading);
  }

  function renderPanel(dimension, data, payload) {
    const panel = element("article", "token-panel");
    panel.dataset.dimension = dimension.key;
    const series = Array.isArray(data.series) ? data.series : [];
    const hidden = hiddenSet(dimension.key);
    const visible = series.filter((item) => !hidden.has(item.key));
    const visibleTotal = visible.reduce((sum, item) => sum + metricTotal(item), 0);
    const allTotal = series.reduce((sum, item) => sum + metricTotal(item), 0);

    const head = element("div", "token-panel-head");
    const title = element("div");
    title.append(element("h3", "", dimension.label), element("span", "token-panel-detail", dimension.detail));
    const total = element("div", "token-panel-total");
    total.append(element("strong", "", compact(visibleTotal)), element("span", "", visibleTotal === allTotal ? "tokens" : `of ${compact(allTotal)} tokens shown`));
    head.append(title, total);
    panel.appendChild(head);

    panel.appendChild(renderLegend(dimension.key, series, hidden));
    panel.appendChild(renderChart(dimension, visible, series, payload));
    panel.appendChild(renderTable(dimension, series, hidden, allTotal));
    return panel;
  }

  function renderLegend(dimensionKey, series, hidden) {
    const legend = element("div", "token-legend");
    legend.setAttribute("role", "group");
    legend.setAttribute("aria-label", "Series (click to hide or show)");
    series.forEach((item, index) => {
      const isHidden = hidden.has(item.key);
      const chip = element("button", `token-chip${isHidden ? " is-off" : ""}`);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(!isHidden));
      chip.title = isHidden ? "Show this series" : "Hide this series";
      const swatch = element("i", "token-swatch");
      swatch.style.setProperty("--swatch", seriesColor(item, index));
      chip.append(swatch, element("span", "", item.label || item.key));
      chip.addEventListener("click", () => {
        setHidden(dimensionKey, item.key, !isHidden);
        renderPanels();
      });
      legend.appendChild(chip);
    });
    if (!series.length) legend.appendChild(element("span", "token-panel-detail", "No token usage recorded in this range."));
    return legend;
  }

  function renderChart(dimension, visible, allSeries, payload) {
    const frame = element("div", "chart-frame token-chart");
    const buckets = Array.isArray(payload.buckets) ? payload.buckets : [];
    if (!buckets.length || !visible.length) {
      frame.appendChild(element("div", "chart-empty", allSeries.length ? "Every series in this layer is hidden." : "No token usage recorded in this range."));
      return frame;
    }
    const compactLayout = window.innerWidth < 620;
    const width = compactLayout ? 420 : 1440;
    const height = compactLayout ? 240 : 300;
    const pad = { top: 16, right: 16, bottom: 34, left: compactLayout ? 54 : 70 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const columns = visible.map((item) => ({ item, color: seriesColor(item, allSeries.indexOf(item)), values: metricPoints(item) }));
    const stackTotals = buckets.map((_, index) => columns.reduce((sum, column) => sum + (column.values[index] || 0), 0));
    const yMaximum = niceMaximum(Math.max(...stackTotals));
    const slot = plotWidth / buckets.length;
    const barWidth = Math.max(1, Math.min(24, slot - 2));

    const svg = svgElement("svg", "token-column-chart", { viewBox: `0 0 ${width} ${height}`, role: "img" });
    svg.setAttribute("aria-label", `${dimension.label}: stacked token usage per ${bucketWord(payload.bucket_seconds)}`);
    for (let index = 0; index <= 4; index += 1) {
      const value = yMaximum * (4 - index) / 4;
      const y = pad.top + plotHeight * index / 4;
      svg.appendChild(svgElement("line", "chart-grid-line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y }));
      const label = svgElement("text", "chart-y-label", { x: pad.left - 10, y: y + 4, "text-anchor": "end" });
      label.textContent = compact(value);
      svg.appendChild(label);
    }

    buckets.forEach((bucket, index) => {
      const x = pad.left + index * slot + (slot - barWidth) / 2;
      let base = pad.top + plotHeight;
      const group = svgElement("g", "token-column", { tabindex: "0" });
      columns.forEach((column, position) => {
        const value = column.values[index] || 0;
        if (value <= 0) return;
        const segmentHeight = value / yMaximum * plotHeight;
        const top = base - segmentHeight;
        // 2px surface gap between stacked segments when the segment is tall enough.
        const gap = position > 0 && segmentHeight > 4 ? 2 : 0;
        group.appendChild(svgElement("rect", "token-segment-rect", {
          x: x.toFixed(2),
          y: top.toFixed(2),
          width: barWidth.toFixed(2),
          height: Math.max(0.5, segmentHeight - gap).toFixed(2),
          fill: column.color,
        }));
        base = top;
      });
      group.appendChild(svgElement("rect", "token-hit", {
        x: (pad.left + index * slot).toFixed(2),
        y: pad.top,
        width: slot.toFixed(2),
        height: plotHeight,
      }));
      const show = (event) => showTooltip(event, frame, bucket, payload.bucket_seconds, columns, index, stackTotals[index]);
      group.addEventListener("pointermove", show);
      group.addEventListener("focus", show);
      group.addEventListener("pointerleave", hideTooltip);
      group.addEventListener("blur", hideTooltip);
      svg.appendChild(group);
      const tick = tickLabel(buckets, index, payload.bucket_seconds, compactLayout);
      if (tick) {
        const label = svgElement("text", "chart-x-label", { x: (pad.left + index * slot).toFixed(2), y: height - 10, "text-anchor": "middle" });
        label.textContent = tick;
        svg.appendChild(label);
        svg.appendChild(svgElement("line", "token-tick", { x1: pad.left + index * slot, x2: pad.left + index * slot, y1: pad.top + plotHeight, y2: pad.top + plotHeight + 5 }));
      }
    });
    svg.appendChild(svgElement("line", "token-baseline", { x1: pad.left, x2: width - pad.right, y1: pad.top + plotHeight, y2: pad.top + plotHeight }));
    frame.appendChild(svg);
    return frame;
  }

  function bucketWord(seconds) {
    const value = finite(seconds) || 3600;
    if (value >= 86400) return "day";
    if (value === 3600) return "hour";
    return `${Math.round(value / 3600)} hours`;
  }

  function tooltipNode() {
    let tip = byId("token-tooltip");
    if (!tip) {
      tip = element("div", "token-tooltip");
      tip.id = "token-tooltip";
      tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    return tip;
  }

  function showTooltip(event, frame, bucket, bucketSeconds, columns, index, total) {
    const tip = tooltipNode();
    const rows = [element("div", "token-tooltip-title", `${bucketLabel(bucket, bucketSeconds, true)} · ${compact(total)} tokens`)];
    for (const column of [...columns].reverse()) {
      const value = column.values[index] || 0;
      const row = element("div", "token-tooltip-row");
      const key = element("i", "token-tooltip-key");
      key.style.setProperty("--swatch", column.color);
      row.append(key, element("strong", "", compact(value)), element("span", "", column.item.label || column.item.key));
      rows.push(row);
    }
    tip.replaceChildren(...rows);
    tip.classList.add("is-visible");
    const rect = frame.getBoundingClientRect();
    const pointX = event && event.clientX ? event.clientX : rect.left + rect.width / 2;
    const pointY = event && event.clientY ? event.clientY : rect.top + 40;
    const tipWidth = tip.offsetWidth || 220;
    const left = Math.min(window.innerWidth - tipWidth - 12, Math.max(12, pointX + 14));
    tip.style.left = `${left + window.scrollX}px`;
    tip.style.top = `${pointY + window.scrollY + 14}px`;
  }

  function hideTooltip() {
    const tip = byId("token-tooltip");
    if (tip) tip.classList.remove("is-visible");
  }

  function renderTable(dimension, series, hidden, allTotal) {
    const table = element("table", "token-table");
    const caption = element("caption", "sr-only", `${dimension.label} token totals`);
    const head = element("thead");
    const headRow = element("tr");
    for (const name of ["Series", "Tokens", "Share", "Input", "Cached input", "Output"]) {
      const cell = element("th", "", name);
      cell.scope = "col";
      headRow.appendChild(cell);
    }
    head.appendChild(headRow);
    const body = element("tbody");
    series.forEach((item, index) => {
      const totals = item.totals || {};
      const row = element("tr", hidden.has(item.key) ? "is-off" : "");
      const name = element("td", "token-table-name");
      const swatch = element("i", "token-swatch");
      swatch.style.setProperty("--swatch", seriesColor(item, index));
      name.append(swatch, element("span", "", item.label || item.key));
      if (item.detail) name.appendChild(element("small", "", item.detail));
      row.append(
        name,
        element("td", "", compact(metricTotal(item))),
        element("td", "", percent(metricTotal(item), allTotal)),
        element("td", "", compact(totals.input)),
        element("td", "", compact(totals.cached_input)),
        element("td", "", compact(totals.output)),
      );
      body.appendChild(row);
    });
    table.append(caption, head, body);
    const wrap = element("div", "token-table-wrap");
    wrap.appendChild(table);
    return wrap;
  }

  function renderFreshness(payload) {
    const node = byId("token-usage-freshness");
    if (!payload) {
      node.textContent = view.error || "Ledger pending";
      return;
    }
    const coverage = payload.coverage || {};
    const sources = Array.isArray(coverage.sources) ? coverage.sources : [];
    const fresh = sources.filter((item) => !item.stale).length;
    const parts = [];
    if (sources.length) parts.push(`${fresh}/${sources.length} sources current`);
    parts.push(`Collected ${ageText(coverage.last_collected_at || payload.generated_at)}`);
    node.textContent = parts.join(" · ");
    node.classList.toggle("is-stale", Boolean(coverage.stale));
    const note = byId("token-usage-note");
    const stale = sources.filter((item) => item.stale).map((item) => item.label || item.name);
    note.textContent = payload.error
      ? payload.error
      : stale.length
        ? `Not current: ${stale.join(", ")}. Their last collected hours stay in the chart; newer usage appears once they report again.`
        : (payload.method || "Hourly totals from the engine's own per-turn token records. Hidden layers and series are remembered in this browser only.");
  }

  async function load(force) {
    if (!prefs.enabled || view.loading) return;
    if (!force && Date.now() - view.lastLoaded < REFRESH_MS) return;
    view.loading = true;
    byId("token-usage-panels").classList.add("is-refreshing");
    try {
      const response = await fetch(`/api/v1/token-usage?span=${encodeURIComponent(prefs.range)}`, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`token_usage_http_${response.status}`);
      view.payload = await response.json();
      view.error = null;
      view.lastLoaded = Date.now();
    } catch (error) {
      view.error = "Token ledger is unavailable right now.";
    } finally {
      view.loading = false;
    }
    renderControls(view.payload);
    renderFreshness(view.payload);
    renderPanels();
  }

  function setEnabled(enabled) {
    prefs.enabled = enabled;
    savePrefs();
    const section = byId("token-usage");
    section.classList.toggle("is-collapsed", !enabled);
    byId("token-usage-body").hidden = !enabled;
    const toggle = byId("token-usage-toggle");
    toggle.setAttribute("aria-expanded", String(enabled));
    toggle.textContent = enabled ? "Hide ledger" : "Show ledger";
    if (enabled) load(true);
  }

  function initialize() {
    const section = byId("token-usage");
    if (!section) return;
    byId("token-usage-toggle").addEventListener("click", () => setEnabled(!prefs.enabled));
    for (const button of document.querySelectorAll(".zone-option[data-zone]")) {
      button.addEventListener("click", () => window.setTimeout(renderPanels, 0));
    }
    renderControls(null);
    setEnabled(prefs.enabled);
    // Lazy: only poll while the ledger is shown and the tab is visible.
    window.setInterval(() => {
      if (prefs.enabled && document.visibilityState === "visible") load(false);
    }, REFRESH_MS);
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(renderPanels, 150);
    });
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
