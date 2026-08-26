(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const SIGNAL_LABELS = {
    browser: "Browser checks",
    host_health: "Host health",
    performance: "Performance",
    slo: "SLO",
    red: "RED metrics",
    tls: "TLS",
    dns: "DNS",
    container_health: "Containers",
    proxy: "Reverse proxy",
    meta: "Monitor integrity",
  };

  const model = {
    range: "24h",
    summary: null,
    selectedDomain: null,
    groupFilter: null,
    collapsedGroups: new Set(),
    groupStateInitialized: false,
    requestSequence: 0,
  };

  const byId = (id) => document.getElementById(id);

  function createElement(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function createSvgElement(tag, attributes = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function numberOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatCount(value) {
    const number = numberOrNull(value);
    return number === null ? "—" : new Intl.NumberFormat("en-US").format(number);
  }

  function formatPercent(value, digits = 2) {
    const number = numberOrNull(value);
    return number === null ? "—" : `${number.toFixed(digits)}%`;
  }

  function formatMilliseconds(value) {
    const number = numberOrNull(value);
    if (number === null) return "—";
    if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}s`;
    return `${Math.round(number)}ms`;
  }

  function formatDuration(value) {
    const seconds = numberOrNull(value);
    if (seconds === null) return "unavailable";
    if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(seconds < 21600 ? 1 : 0)}h`;
    return `${(seconds / 86400).toFixed(seconds < 604800 ? 1 : 0)}d`;
  }

  function formatDateTime(value) {
    const timestamp = numberOrNull(value);
    if (timestamp === null) return "Unavailable";
    return new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    }).format(new Date(timestamp * 1000));
  }

  function formatRelative(value, reference = Date.now() / 1000) {
    const timestamp = numberOrNull(value);
    if (timestamp === null) return "Time unavailable";
    const age = Math.max(0, reference - timestamp);
    if (age < 5) return "just now";
    return `${formatDuration(age)} ago`;
  }

  function titleCase(value) {
    return String(value || "unknown")
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function statusClass(status) {
    if (["healthy", "fresh", "up", "pass", "ok"].includes(status)) return "is-healthy";
    if (["critical", "stale", "down", "fail"].includes(status)) return "is-critical";
    return "is-attention";
  }

  function setStatusLabel(node, label, status) {
    node.textContent = label;
    node.className = `status-label ${statusClass(status)}`;
  }

  function showError(message) {
    const error = byId("dash-error");
    error.textContent = message;
    error.hidden = false;
  }

  function clearError() {
    const error = byId("dash-error");
    error.textContent = "";
    error.hidden = true;
  }

  async function getJson(path) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error("Your PitchAI SSO session is unavailable. Return to Tools and sign in again.");
      }
      throw new Error(`Monitoring request failed with HTTP ${response.status}.`);
    }
    const payload = await response.json();
    if (!payload || payload.ok !== true) throw new Error("Monitoring returned an invalid response.");
    return payload;
  }

  function renderPosture(summary) {
    const incidents = Array.isArray(summary.incidents) ? summary.incidents : [];
    const freshness = summary.freshness || {};
    let posture = "healthy";
    let title = "All monitored systems healthy";
    let detail = `State refreshed ${formatRelative(freshness.state_updated_at_ts, summary.generated_at_ts)}`;

    if (freshness.status === "stale" || freshness.status === "unknown") {
      posture = "critical";
      title = freshness.status === "stale" ? "Monitoring state is stale" : "Monitoring state unavailable";
      detail = "Current production evidence cannot be trusted until the monitor recovers.";
    } else if (incidents.length > 0) {
      posture = incidents.some((incident) => incident.severity === "critical") ? "critical" : "attention";
      const expectedOnly = incidents.every((incident) => incident.severity === "expected");
      title = expectedOnly
        ? `${incidents.length} expected dashboard-only ${incidents.length === 1 ? "outage" : "outages"}`
        : `${incidents.length} current ${incidents.length === 1 ? "problem" : "problems"}`;
      detail = expectedOnly
        ? "Visible for awareness; Telegram alerts are suppressed by explicit policy."
        : "Review the incidents and affected checks below.";
    }

    const container = byId("overall-posture");
    container.className = `posture is-${posture}`;
    byId("overall-posture-title").textContent = title;
    byId("overall-posture-detail").textContent = detail;
  }

  function renderEvidence(summary) {
    const freshness = summary.freshness || {};
    const services = summary.service_health || {};
    const e2e = summary.e2e || {};
    const daily = summary.daily_status || {};

    byId("kpi-freshness").textContent = freshness.status === "fresh" ? formatDuration(freshness.age_seconds) : titleCase(freshness.status);
    byId("kpi-freshness-detail").textContent = freshness.status === "fresh"
      ? `Current · expected every ${formatDuration(freshness.interval_seconds)}`
      : `Threshold ${formatDuration(freshness.stale_after_seconds)}`;

    byId("kpi-services").textContent = `${formatCount(services.healthy)}/${formatCount(services.enabled)}`;
    const unavailable = numberOrNull(services.unknown) || 0;
    const expectedDown = numberOrNull(services.expected_down) || 0;
    const alertableDown = numberOrNull(services.alertable_down) || 0;
    if (services.down && unavailable) {
      byId("kpi-services-detail").textContent = `${formatCount(alertableDown)} alertable · ${formatCount(expectedDown)} expected · ${formatCount(unavailable)} without observations`;
    } else if (alertableDown && expectedDown) {
      byId("kpi-services-detail").textContent = `${formatCount(alertableDown)} alertable · ${formatCount(expectedDown)} expected/dashboard only`;
    } else if (alertableDown) {
      byId("kpi-services-detail").textContent = `${formatCount(alertableDown)} requiring attention`;
    } else if (expectedDown) {
      byId("kpi-services-detail").textContent = `${formatCount(expectedDown)} expected · dashboard only, no alerts`;
    } else if (unavailable) {
      byId("kpi-services-detail").textContent = `${formatCount(unavailable)} without observations`;
    } else {
      byId("kpi-services-detail").textContent = `${formatCount(services.disabled)} disabled · no current outage`;
    }

    byId("kpi-e2e").textContent = e2e.total_tests === null || e2e.total_tests === undefined
      ? "Unavailable"
      : `${formatCount(e2e.passing_tests)}/${formatCount(e2e.total_tests)}`;
    byId("kpi-e2e-detail").textContent = e2e.latest_run_at_ts
      ? `Latest run ${formatRelative(e2e.latest_run_at_ts, summary.generated_at_ts)} · ${formatCount(e2e.disabled_tests)} disabled`
      : "No completed E2E run found";

    byId("kpi-availability").textContent = formatPercent(daily.availability_pct, 3);
    byId("kpi-availability-detail").textContent = `${formatCount(daily.successful_observations)} of ${formatCount(daily.observations)} successful`;
  }

  function renderIncidents(summary) {
    const container = byId("incident-list");
    const incidents = Array.isArray(summary.incidents) ? summary.incidents : [];
    byId("incident-count").textContent = formatCount(incidents.length);
    container.replaceChildren();

    if (incidents.length === 0) {
      container.append(createElement("p", "empty-state is-healthy", "No current incidents. All latest effective checks are healthy."));
      return;
    }

    incidents.forEach((incident) => {
      const item = createElement("article", `incident ${incident.severity === "critical" ? "is-critical" : ""}`);
      item.append(createElement("span", "incident__marker"));
      const copy = createElement("div");
      copy.append(createElement("strong", "", incident.title || titleCase(incident.kind)));
      copy.append(createElement("p", "", incident.detail || "No additional detail was recorded."));
      item.append(copy);
      const time = createElement("time", "", formatRelative(incident.observed_at_ts, summary.generated_at_ts));
      if (incident.observed_at_ts) time.dateTime = new Date(Number(incident.observed_at_ts) * 1000).toISOString();
      item.append(time);
      container.append(item);
    });
  }

  function renderDailyStatus(summary) {
    const daily = summary.daily_status || {};
    const status = daily.status || "unknown";
    setStatusLabel(byId("daily-status-label"), titleCase(status), status);
    byId("daily-observations").textContent = formatCount(daily.observations);
    byId("daily-problems").textContent = formatCount(daily.problem_events);
    byId("daily-recoveries").textContent = formatCount(daily.recoveries);
    byId("daily-latest-event").textContent = daily.latest_event_at_ts
      ? formatRelative(daily.latest_event_at_ts, summary.generated_at_ts)
      : "None recorded";

    const availability = formatPercent(daily.availability_pct, 3);
    byId("daily-note").textContent = status === "unknown"
      ? "No domain observations were available for the last 24 hours."
      : `${availability} availability across enabled domains during the rolling 24-hour review.`;
  }

  function domainState(domain) {
    if (domain.disabled) return { label: "Disabled", className: "is-disabled" };
    if (!domain.last || domain.last.ok === null || domain.last.ok === undefined) {
      return { label: "Unknown", className: "is-unknown" };
    }
    return domain.last.ok
      ? { label: "Healthy", className: "" }
      : { label: "Down", className: "is-down" };
  }

  function addCell(row, label, content) {
    const cell = createElement("td");
    cell.dataset.label = label;
    if (content instanceof Node) cell.append(content);
    else cell.textContent = String(content);
    row.append(cell);
  }

  function groupState(group) {
    if (group.alertable_down) return { label: `${formatCount(group.down)} down`, className: "is-critical" };
    if (group.expected_down) return { label: `${formatCount(group.expected_down)} expected · no alerts`, className: "is-attention" };
    if (group.unknown) return { label: `${formatCount(group.unknown)} unknown`, className: "is-attention" };
    return { label: `${formatCount(group.healthy)}/${formatCount(group.enabled)} healthy`, className: "is-healthy" };
  }

  function renderDomainGroups(summary) {
    const container = byId("domain-group-grid");
    const groups = Array.isArray(summary.domain_groups) ? summary.domain_groups : [];
    const inventory = summary.inventory || {};
    container.replaceChildren();

    const makeButton = ({ id, label, detail, status }) => {
      const button = createElement("button", `domain-group-card ${statusClass(status)}`);
      button.type = "button";
      button.dataset.group = id || "all";
      button.setAttribute("aria-pressed", String((model.groupFilter || "all") === (id || "all")));
      button.append(createElement("strong", "", label));
      button.append(createElement("span", "", detail));
      button.addEventListener("click", () => {
        model.groupFilter = id || null;
        if (id) model.collapsedGroups.delete(id);
        renderDomainGroups(summary);
        renderDomains(summary);
        const visible = (summary.domains || []).find((domain) => !id || domain.group === id);
        const selected = (summary.domains || []).find((domain) => domain.domain === model.selectedDomain);
        if (visible && (!selected || (id && selected.group !== id))) selectDomain(visible.domain);
      });
      return button;
    };

    container.append(makeButton({
      id: null,
      label: "All groups",
      detail: `${formatCount(inventory.active_domains)} active checks`,
      status: groups.some((group) => group.alertable_down)
        ? "critical"
        : (groups.some((group) => group.expected_down) ? "attention" : "healthy"),
    }));
    groups.forEach((group) => {
      const state = groupState(group);
      container.append(makeButton({ id: group.id, label: group.label, detail: state.label, status: state.className.replace("is-", "") }));
    });

    const reviewed = inventory.reviewed_at ? `reviewed ${inventory.reviewed_at}` : "review date unavailable";
    const orphaned = numberOrNull(inventory.orphaned_state_domains) || 0;
    const orphanedNote = orphaned ? ` · ${formatCount(orphaned)} historical state rows excluded` : "";
    byId("domain-inventory-note").textContent = `${formatCount(inventory.active_domains)} monitored domains · ${formatCount(inventory.groups)} groups · ${formatCount(inventory.retired_domains)} classified exclusions${orphanedNote} · ${reviewed}`;
  }

  function groupMatchesQuery(domain, query) {
    if (!query) return true;
    return [domain.domain, domain.label, domain.group_label, domain.environment, domain.kind]
      .some((value) => String(value || "").toLowerCase().includes(query));
  }

  function appendDomainRow(tbody, domain) {
    const row = createElement("tr", domain.domain === model.selectedDomain ? "is-selected" : "");
    row.tabIndex = 0;
    row.dataset.domain = domain.domain;
    row.dataset.group = domain.group || "unconfigured";
    row.setAttribute("aria-label", `Inspect ${domain.domain}`);
    if (domain.domain === model.selectedDomain) row.setAttribute("aria-current", "true");

    const state = domainState(domain);
    const statusCell = createElement("span", "health-state-stack");
    statusCell.append(createElement("span", `health-state ${state.className}`, state.label));
    if (domain.alert_policy && domain.alert_policy.telegram_enabled === false) {
      statusCell.append(createElement(
        "span",
        "alert-policy-state",
        state.label === "Down" ? "Expected · no alerts" : "Dashboard only"
      ));
    }
    addCell(row, "Status", statusCell);

    const domainCell = createElement("span");
    domainCell.append(createElement("span", "domain-name", domain.domain));
    const note = domain.disabled_reason || [domain.label !== domain.domain ? domain.label : null, domain.environment].filter(Boolean).join(" · ");
    if (note) domainCell.append(createElement("span", "domain-note", note));
    addCell(row, "Domain", domainCell);
    addCell(row, "HTTP", formatMilliseconds(domain.last && domain.last.http_ms));
    addCell(row, "Browser", formatMilliseconds(domain.last && domain.last.browser_ms));
    addCell(row, "24h", formatPercent(domain.availability_24h && domain.availability_24h.ok_pct, 2));
    addCell(row, "HTTP p95", formatMilliseconds(domain.latency_24h && domain.latency_24h.http_p95_ms));

    const select = () => selectDomain(domain.domain);
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    tbody.append(row);
  }

  function renderDomains(summary) {
    const tbody = byId("domains-body");
    const query = byId("domain-filter").value.trim().toLowerCase();
    const allDomains = Array.isArray(summary.domains) ? summary.domains : [];
    const domains = allDomains.filter((domain) =>
      groupMatchesQuery(domain, query) && (query || !model.groupFilter || domain.group === model.groupFilter)
    );
    tbody.replaceChildren();

    if (domains.length === 0) {
      const row = createElement("tr");
      const cell = createElement("td", "empty-state", query ? "No domains match this filter." : "No monitored domains were returned.");
      cell.colSpan = 6;
      row.append(cell);
      tbody.append(row);
      return;
    }

    const groups = Array.isArray(summary.domain_groups) ? summary.domain_groups : [];
    groups.forEach((group) => {
      const members = domains.filter((domain) => domain.group === group.id);
      if (!members.length) return;
      const collapsed = !query && model.collapsedGroups.has(group.id);
      const groupRow = createElement("tr", "domain-group-row");
      groupRow.dataset.group = group.id;
      const cell = createElement("td");
      cell.colSpan = 6;
      const toggle = createElement("button", "domain-group-toggle");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(!collapsed));
      toggle.append(createElement("span", "domain-group-toggle__chevron", collapsed ? "+" : "−"));
      const copy = createElement("span", "domain-group-toggle__copy");
      copy.append(createElement("strong", "", group.label));
      copy.append(createElement("small", "", group.description || `${formatCount(group.total)} monitored domains`));
      toggle.append(copy);
      const state = groupState(group);
      toggle.append(createElement("span", `domain-group-toggle__status ${state.className}`, state.label));
      toggle.addEventListener("click", () => {
        if (model.collapsedGroups.has(group.id)) model.collapsedGroups.delete(group.id);
        else model.collapsedGroups.add(group.id);
        renderDomains(summary);
      });
      cell.append(toggle);
      groupRow.append(cell);
      tbody.append(groupRow);
      if (!collapsed) members.forEach((domain) => appendDomainRow(tbody, domain));
    });
  }

  function chartEmpty(svg, message) {
    svg.replaceChildren();
    const text = createSvgElement("text", {
      x: 320,
      y: 61,
      "text-anchor": "middle",
      fill: "#84938e",
      "font-size": 12,
      "font-family": "system-ui, sans-serif",
    });
    text.textContent = message;
    svg.append(text);
  }

  function pointsPath(points) {
    return points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  }

  function renderAvailabilityChart(samples) {
    const svg = byId("chart-domain-ok");
    if (!samples.length) {
      chartEmpty(svg, "No samples in this window");
      return;
    }
    const points = samples.map((sample, index) => [
      samples.length === 1 ? 320 : 12 + (index / (samples.length - 1)) * 616,
      sample.ok ? 24 : 93,
    ]);
    const fill = createSvgElement("path", {
      d: `${pointsPath(points)} L628,106 L12,106 Z`,
      fill: "rgba(8, 119, 94, 0.10)",
      stroke: "none",
    });
    const line = createSvgElement("path", {
      d: pointsPath(points),
      fill: "none",
      stroke: "#08775e",
      "stroke-width": 3,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "vector-effect": "non-scaling-stroke",
    });
    svg.replaceChildren(fill, line);
  }

  function renderLatencyChart(samples) {
    const svg = byId("chart-domain-latency");
    const values = samples.flatMap((sample) => [numberOrNull(sample.http_ms), numberOrNull(sample.browser_ms)]).filter((value) => value !== null);
    if (!samples.length || !values.length) {
      chartEmpty(svg, "No latency samples in this window");
      return;
    }
    const maximum = Math.max(...values, 1);
    const series = [
      { key: "http_ms", color: "#08775e" },
      { key: "browser_ms", color: "#c0801b" },
    ];
    const paths = [];
    series.forEach(({ key, color }) => {
      let segment = [];
      const segments = [];
      samples.forEach((sample, index) => {
        const value = numberOrNull(sample[key]);
        if (value === null) {
          if (segment.length) segments.push(segment);
          segment = [];
          return;
        }
        const x = samples.length === 1 ? 320 : 12 + (index / (samples.length - 1)) * 616;
        const y = 102 - (value / maximum) * 88;
        segment.push([x, y]);
      });
      if (segment.length) segments.push(segment);
      segments.forEach((points) => {
        paths.push(createSvgElement("path", {
          d: pointsPath(points),
          fill: "none",
          stroke: color,
          "stroke-width": 2.5,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          "vector-effect": "non-scaling-stroke",
        }));
      });
    });
    svg.replaceChildren(...paths);
  }

  async function selectDomain(domainName) {
    model.selectedDomain = domainName;
    if (model.summary) renderDomains(model.summary);
    const domain = (model.summary && model.summary.domains || []).find((item) => item.domain === domainName);
    if (!domain) return;

    byId("domain-detail-title").textContent = domainName;
    const policyMeta = domain.alert_policy && domain.alert_policy.telegram_enabled === false
      ? " · Dashboard only · no Telegram alerts"
      : " · Critical alerting";
    byId("selected-domain-meta").textContent = `${domain.group_label || "Unconfigured"} · ${titleCase(domain.environment)} · ${titleCase(domain.kind)}${policyMeta}`;
    const state = domainState(domain);
    setStatusLabel(byId("selected-domain-status"), state.label, state.label.toLowerCase());
    byId("selected-domain-availability").textContent = formatPercent(domain.availability_24h && domain.availability_24h.ok_pct, 2);
    byId("selected-domain-latency").textContent = `HTTP ${formatMilliseconds(domain.latency_24h && domain.latency_24h.http_p95_ms)} · Browser ${formatMilliseconds(domain.latency_24h && domain.latency_24h.browser_p95_ms)}`;
    byId("selected-domain-range").textContent = `Loading ${model.range} production history…`;

    const sequence = ++model.requestSequence;
    try {
      const payload = await getJson(`/dashboard/api/v1/monitoring/domains/${encodeURIComponent(domainName)}/series?range=${encodeURIComponent(model.range)}`);
      if (sequence !== model.requestSequence || domainName !== model.selectedDomain) return;
      const samples = Array.isArray(payload.samples) ? payload.samples : [];
      renderAvailabilityChart(samples);
      renderLatencyChart(samples);
      byId("selected-domain-range").textContent = `${formatCount(samples.length)} retained samples · ${formatDateTime(payload.since_ts)} to ${formatDateTime(payload.until_ts)}`;
    } catch (error) {
      if (sequence !== model.requestSequence) return;
      chartEmpty(byId("chart-domain-ok"), "History request failed");
      chartEmpty(byId("chart-domain-latency"), "History request failed");
      byId("selected-domain-range").textContent = error instanceof Error ? error.message : "History request failed.";
    }
  }

  function signalState(key, value) {
    if (!value || typeof value !== "object") return { status: "unknown", detail: "No latest result" };
    if (key === "browser") {
      return value.degraded_active
        ? { status: "attention", detail: "Browser launch degraded" }
        : { status: "healthy", detail: "Browser checks available" };
    }
    if (value.last_ok === true) {
      const successes = numberOrNull(value.success_streak);
      return { status: "healthy", detail: successes === null ? "Latest check passed" : `${formatCount(successes)} successful cycles` };
    }
    if (value.last_ok === false) {
      const failures = numberOrNull(value.fail_streak);
      return { status: "attention", detail: failures === null ? "Latest check degraded" : `${formatCount(failures)} failing cycles` };
    }
    return { status: "unknown", detail: "No latest result" };
  }

  function renderSignals(summary) {
    const container = byId("signal-grid");
    container.replaceChildren();
    const signals = summary.signals || {};
    Object.entries(SIGNAL_LABELS).forEach(([key, label]) => {
      const signal = signalState(key, signals[key]);
      const item = createElement("article", `signal-item ${statusClass(signal.status)}`);
      item.append(createElement("span", "signal-item__dot"));
      const copy = createElement("div");
      copy.append(createElement("strong", "", label));
      copy.append(createElement("small", "", signal.detail));
      item.append(copy);
      container.append(item);
    });

    const range = summary.history_range || {};
    byId("history-range").textContent = range.min_ts && range.max_ts
      ? `${formatDateTime(range.min_ts)} — ${formatDateTime(range.max_ts)}`
      : "History unavailable";
  }

  function eventDetail(event) {
    const pieces = [];
    if (event.domain) pieces.push(String(event.domain));
    if (event.status_code) pieces.push(`HTTP ${event.status_code}`);
    if (Array.isArray(event.violations) && event.violations.length) pieces.push(event.violations.slice(0, 3).map(String).join(" · "));
    if (event.signal) pieces.push(String(event.signal).replace(/_/g, " "));
    if (pieces.length) return pieces.join(" · ");
    const kind = String(event.kind || "").toLowerCase();
    if (kind.endsWith("_recovered") || kind.endsWith("_up") || kind.endsWith("_healthy")) {
      return "The effective production signal returned to healthy.";
    }
    if (kind.endsWith("_degraded") || kind.endsWith("_down") || kind.endsWith("_failed")) {
      return "The effective production signal requires attention.";
    }
    return "Production monitor state changed.";
  }

  function renderEvents(summary) {
    const container = byId("events-list");
    const events = (Array.isArray(summary.events) ? summary.events : [])
      .slice()
      .sort((left, right) => (numberOrNull(right.ts) || 0) - (numberOrNull(left.ts) || 0))
      .slice(0, 8);
    container.replaceChildren();
    if (!events.length) {
      container.append(createElement("p", "empty-state", "No monitor events were recorded in this window."));
      return;
    }
    events.forEach((event) => {
      const item = createElement("article", "event");
      const copy = createElement("div");
      copy.append(createElement("span", "event__kind", titleCase(event.kind)));
      copy.append(createElement("strong", "", eventDetail(event)));
      item.append(copy);
      const time = createElement("time", "", formatRelative(event.ts, summary.generated_at_ts));
      if (event.ts) time.dateTime = new Date(Number(event.ts) * 1000).toISOString();
      item.append(time);
      container.append(item);
    });
  }

  function safeDispatcherUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" && url.hostname === "dispatch.pitchai.net" ? url.href : null;
    } catch (_error) {
      return null;
    }
  }

  function diagnosticTimestamp(item) {
    return numberOrNull(item.ts) || numberOrNull(item.created_at_ts) || 0;
  }

  function renderDiagnostics(summary) {
    const monitorRuns = summary.dispatch && Array.isArray(summary.dispatch.recent) ? summary.dispatch.recent : [];
    const registryRuns = Array.isArray(summary.e2e_registry_dispatch) ? summary.e2e_registry_dispatch : [];
    const diagnostics = [...monitorRuns, ...registryRuns]
      .sort((left, right) => diagnosticTimestamp(right) - diagnosticTimestamp(left))
      .slice(0, 8);
    const container = byId("diagnostic-list");
    container.replaceChildren();
    if (!diagnostics.length) {
      container.append(createElement("p", "empty-state", "No recent automated investigations in this window."));
      return;
    }
    diagnostics.forEach((diagnostic) => {
      const item = createElement("article", "diagnostic");
      const copy = createElement("div");
      copy.append(createElement("span", "diagnostic__state", titleCase(diagnostic.queue_state || diagnostic.state_key || "Investigation")));
      copy.append(createElement("strong", "", titleCase(diagnostic.title || diagnostic.state_key || "Automated investigation")));
      const message = String(diagnostic.agent_message || diagnostic.error_message || "No conclusion recorded yet.").slice(0, 500);
      copy.append(createElement("p", "", message));
      const href = safeDispatcherUrl(diagnostic.ui_url);
      if (href) {
        const link = createElement("a", "", "Open investigation");
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        copy.append(link);
      }
      item.append(copy);
      const time = createElement("time", "", formatRelative(diagnosticTimestamp(diagnostic), summary.generated_at_ts));
      item.append(time);
      container.append(item);
    });
  }

  function renderSummary(summary) {
    model.summary = summary;
    renderPosture(summary);
    renderEvidence(summary);
    renderIncidents(summary);
    renderDailyStatus(summary);
    renderSignals(summary);
    renderEvents(summary);
    renderDiagnostics(summary);
    byId("loaded-at").textContent = formatDateTime(summary.loaded_at_ts);

    const domains = Array.isArray(summary.domains) ? summary.domains : [];
    if (!model.selectedDomain || !domains.some((domain) => domain.domain === model.selectedDomain)) {
      const preferred = domains.find((domain) => !domain.disabled) || domains[0];
      model.selectedDomain = preferred ? preferred.domain : null;
    }
    if (!model.groupStateInitialized) {
      const groups = Array.isArray(summary.domain_groups) ? summary.domain_groups : [];
      const attention = groups.find((group) => group.down || group.unknown);
      const preferredDomain = domains.find((domain) => domain.domain === model.selectedDomain);
      model.groupFilter = attention ? attention.id : (preferredDomain ? preferredDomain.group : (groups[0] && groups[0].id));
      groups
        .filter((group) => group.id !== model.groupFilter && !group.down && !group.unknown)
        .forEach((group) => model.collapsedGroups.add(group.id));
      model.groupStateInitialized = true;
    }
    renderDomainGroups(summary);
    renderDomains(summary);
    if (model.selectedDomain) selectDomain(model.selectedDomain);
    else {
      chartEmpty(byId("chart-domain-ok"), "No monitored domains");
      chartEmpty(byId("chart-domain-latency"), "No monitored domains");
    }
  }

  async function loadDashboard() {
    const button = byId("reload");
    button.classList.add("is-loading");
    button.disabled = true;
    clearError();
    try {
      const summary = await getJson(`/dashboard/api/v1/monitoring/summary?range=${encodeURIComponent(model.range)}`);
      renderSummary(summary);
      if (summary.error) showError("The monitor reported an incomplete state or configuration. Current values may be partial.");
    } catch (error) {
      showError(error instanceof Error ? error.message : "Monitoring data could not be loaded.");
    } finally {
      button.classList.remove("is-loading");
      button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const range = byId("range");
    model.range = range.value;
    range.addEventListener("change", () => {
      model.range = range.value;
      loadDashboard();
    });
    byId("reload").addEventListener("click", loadDashboard);
    byId("domain-filter").addEventListener("input", () => {
      if (model.summary) renderDomains(model.summary);
    });
    loadDashboard();
  });
})();
