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
    activeTab: "domains",
    expandedIncidents: new Set(),
    incidentEvidence: new Map(),
    incidentStateInitialized: false,
    expandedJourneys: new Set(),
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

  function formatBytes(value) {
    const number = numberOrNull(value);
    if (number === null) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let scaled = Math.max(0, number);
    let index = 0;
    while (scaled >= 1024 && index < units.length - 1) {
      scaled /= 1024;
      index += 1;
    }
    return `${scaled.toFixed(index === 0 || scaled >= 100 ? 0 : 1)} ${units[index]}`;
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

  function appendIncidentField(list, label, value, className = "") {
    const wrapper = createElement("div", className);
    wrapper.append(createElement("dt", "", label));
    wrapper.append(createElement("dd", "", value || "Unavailable"));
    list.append(wrapper);
  }

  function renderIncidentTrend(trend) {
    const wrapper = createElement("div", "incident-trend");
    const points = trend && Array.isArray(trend.points) ? trend.points : [];
    const heading = createElement("div", "incident-trend__heading");
    heading.append(createElement("span", "", "24-hour trend"));
    heading.append(createElement("strong", statusClass(trend && trend.direction), titleCase(trend && trend.direction)));
    wrapper.append(heading);
    const svg = createSvgElement("svg", { viewBox: "0 0 420 72", preserveAspectRatio: "none", role: "img", "aria-label": "Incident trend" });
    svg.classList.add("incident-trend__chart");
    if (points.length < 2) {
      const textNode = createSvgElement("text", { x: 10, y: 42, class: "chart-empty-text" });
      textNode.textContent = "Trend collecting";
      svg.append(textNode);
    } else {
      const pathPoints = points.map((point, index) => {
        const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 420;
        const latency = numberOrNull(point.http_elapsed_ms);
        const ok = point.ok !== false;
        const y = ok ? Math.max(10, 58 - Math.min(42, (latency || 0) / 80)) : 64;
        return [x, y];
      });
      const path = createSvgElement("path", { d: pointsPath(pathPoints), class: "chart-line" });
      svg.append(path);
      points.forEach((point, index) => {
        const [x, y] = pathPoints[index];
        svg.append(createSvgElement("circle", { cx: x, cy: y, r: point.ok === false ? 4 : 2.5, class: point.ok === false ? "chart-point is-down" : "chart-point" }));
      });
    }
    wrapper.append(svg);
    const availability = numberOrNull(trend && trend.availability_pct);
    wrapper.append(createElement("p", "incident-trend__meta", availability === null
      ? `${formatCount(trend && trend.observations)} retained observations`
      : `${formatPercent(availability, 3)} availability · ${formatCount(trend && trend.observations)} observations`));
    return wrapper;
  }

  async function loadIncidentEvidence(incident, incidentId, summary) {
    if (!incident || incident.kind !== "domain_down" || !incident.domain) return;
    if (model.incidentEvidence.has(incidentId)) return;
    const endpoint = incident.evidence_endpoint
      || `/dashboard/api/v1/monitoring/incidents/${encodeURIComponent(incident.domain)}/evidence`;
    model.incidentEvidence.set(incidentId, { loading: true });
    renderIncidents(summary);
    try {
      const payload = await getJson(endpoint);
      model.incidentEvidence.set(incidentId, { ...payload, loading: false });
    } catch (error) {
      model.incidentEvidence.set(incidentId, {
        loading: false,
        data_state: "unavailable",
        error_message: error instanceof Error ? error.message : "On-expand evidence request failed.",
      });
    }
    renderIncidents(summary);
  }

  function renderIncidents(summary) {
    const container = byId("incident-list");
    const incidents = Array.isArray(summary.incidents) ? summary.incidents : [];
    byId("incident-count").textContent = formatCount(incidents.length);
    container.replaceChildren();

    if (incidents.length === 0) {
      container.append(createElement("p", "empty-state is-healthy", "No current incidents. All latest effective checks are healthy."));
      model.expandedIncidents.clear();
      return;
    }

    if (!model.incidentStateInitialized) {
      const firstActionable = incidents.find((incident) => incident.severity === "critical") || incidents[0];
      if (firstActionable) model.expandedIncidents.add(firstActionable.incident_id || `${firstActionable.kind}:0`);
      model.incidentStateInitialized = true;
    }
    const activeIds = new Set(incidents.map((incident, index) => incident.incident_id || `${incident.kind}:${index}`));
    [...model.expandedIncidents].forEach((id) => { if (!activeIds.has(id)) model.expandedIncidents.delete(id); });
    [...model.incidentEvidence.keys()].forEach((id) => { if (!activeIds.has(id)) model.incidentEvidence.delete(id); });

    incidents.forEach((incident, index) => {
      const incidentId = incident.incident_id || `${incident.kind}:${index}`;
      const fetchedEvidence = model.incidentEvidence.get(incidentId) || {};
      const renderedIncident = { ...incident };
      ["status_code", "error_message", "response_excerpt", "content_type"].forEach((key) => {
        if (fetchedEvidence[key] !== null && fetchedEvidence[key] !== undefined) renderedIncident[key] = fetchedEvidence[key];
      });
      const domId = `incident-details-${index}`;
      const expanded = model.expandedIncidents.has(incidentId);
      const item = createElement("article", `incident is-${incident.severity || "warning"}${expanded ? " is-expanded" : ""}`);
      item.dataset.incidentId = incidentId;

      const toggle = createElement("button", "incident__toggle");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-controls", domId);
      toggle.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} details for ${incident.title || titleCase(incident.kind)}`);
      toggle.append(createElement("span", "incident__marker"));
      const copy = createElement("span", "incident__copy");
      const titleRow = createElement("span", "incident__title-row");
      titleRow.append(createElement("strong", "", incident.title || titleCase(incident.kind)));
      titleRow.append(createElement("span", `status-label ${statusClass(incident.current_status || incident.severity)}`, titleCase(incident.current_status || incident.severity)));
      copy.append(titleRow);
      copy.append(createElement("span", "incident__summary", incident.detail || "No additional detail was recorded."));
      toggle.append(copy);
      const timing = createElement("span", "incident__timing");
      const time = createElement("time", "", formatRelative(incident.latest_seen_at_ts || incident.observed_at_ts, summary.generated_at_ts));
      if (incident.latest_seen_at_ts || incident.observed_at_ts) time.dateTime = new Date(Number(incident.latest_seen_at_ts || incident.observed_at_ts) * 1000).toISOString();
      timing.append(time);
      timing.append(createElement("span", "incident__toggle-label", expanded ? "Collapse details" : "Expand details"));
      const chevron = createSvgElement("svg", { viewBox: "0 0 20 20", "aria-hidden": "true" });
      chevron.classList.add("incident__chevron");
      chevron.append(createSvgElement("path", { d: "m5 7.5 5 5 5-5" }));
      timing.append(chevron);
      toggle.append(timing);
      item.append(toggle);

      const details = createElement("div", "incident__details");
      details.id = domId;
      details.hidden = !expanded;
      const fields = createElement("dl", "incident-detail-grid");
      appendIncidentField(fields, "Affected check", renderedIncident.affected_check);
      appendIncidentField(fields, "Domain / service", renderedIncident.domain || renderedIncident.affected_service);
      appendIncidentField(fields, "Current status", titleCase(renderedIncident.current_status));
      appendIncidentField(fields, "Severity", titleCase(renderedIncident.severity));
      appendIncidentField(fields, "First seen", formatDateTime(renderedIncident.first_seen_at_ts));
      appendIncidentField(fields, "Latest seen", formatDateTime(renderedIncident.latest_seen_at_ts || renderedIncident.observed_at_ts));
      appendIncidentField(fields, "Status / error code", renderedIncident.status_code === null || renderedIncident.status_code === undefined ? "Not recorded" : String(renderedIncident.status_code));
      appendIncidentField(fields, "Likely owner / project", renderedIncident.owner_project);
      if (renderedIncident.kind === "database_dependency") {
        appendIncidentField(fields, "Database dependency", renderedIncident.database_dependency);
        appendIncidentField(fields, "App container", renderedIncident.container);
        appendIncidentField(fields, "Failure class", titleCase(renderedIncident.failure_class));
        appendIncidentField(fields, "Failure phase", titleCase(renderedIncident.failure_phase));
        appendIncidentField(fields, "Credential signal", titleCase(renderedIncident.credential_state));
        const routeWeight = numberOrNull(renderedIncident.traffic_weight);
        appendIncidentField(fields, "Production route", [
          titleCase(renderedIncident.traffic_state),
          renderedIncident.traffic_slot ? `${titleCase(renderedIncident.traffic_slot)} slot` : null,
          routeWeight === null ? null : `${routeWeight}% traffic`,
        ].filter(Boolean).join(" · "));
        appendIncidentField(fields, "Alert group", renderedIncident.alert_group || "Not configured");
      }
      const policy = renderedIncident.alert_policy || {};
      const policyLabel = policy.enabled === false
        ? `Dashboard only · ${policy.reason || "Telegram disabled by policy"}`
        : `${policy.channel || "Telegram"} · ${policy.mode || "enabled"}`;
      appendIncidentField(fields, "Alert policy", policyLabel, policy.enabled === false ? "is-policy-quiet" : "");
      const lastSuccess = renderedIncident.last_successful_sample || {};
      appendIncidentField(fields, "Last successful sample", lastSuccess.observed_at_ts
        ? `${formatDateTime(lastSuccess.observed_at_ts)}${lastSuccess.status_code ? ` · HTTP ${lastSuccess.status_code}` : ""}${numberOrNull(lastSuccess.latency_ms) === null ? "" : ` · ${formatMilliseconds(lastSuccess.latency_ms)}`}`
        : "Not retained");
      details.append(fields);

      if (renderedIncident.kind === "domain_down" || renderedIncident.error_message || renderedIncident.response_excerpt) {
        const evidence = createElement("div", "incident-evidence");
        evidence.append(createElement("p", "section-kicker", "Safe failure evidence"));
        if (renderedIncident.error_message) evidence.append(createElement("p", "incident-evidence__error", renderedIncident.error_message));
        if (renderedIncident.response_excerpt) {
          evidence.append(createElement("p", "incident-evidence__label", "Response excerpt · secrets and private data redacted"));
          evidence.append(createElement("pre", "", renderedIncident.response_excerpt));
        } else if (fetchedEvidence.loading) {
          evidence.append(createElement("p", "data-state", "Fetching one bounded, allowlisted public response because this incident was expanded…"));
        } else if (fetchedEvidence.data_state === "recovered") {
          evidence.append(createElement("p", "data-state", "The on-expand public HTTP request has recovered; no failure body was retained."));
        } else if (fetchedEvidence.data_state === "unavailable" || fetchedEvidence.data_state === "request_failed") {
          evidence.append(createElement("p", "data-state", "On-expand evidence is unavailable. Retained status, timing, and trend remain authoritative."));
        } else {
          evidence.append(createElement("p", "data-state", renderedIncident.evidence_state === "not_retained" || renderedIncident.evidence_state === "on_expand"
            ? "Expand this incident to fetch one bounded, allowlisted public response. No extra background probe is added."
            : "No safe textual response excerpt was available for this failure."));
        }
        details.append(evidence);
      }
      details.append(renderIncidentTrend(renderedIncident.trend || {}));
      const action = createElement("div", "incident-action");
      action.append(createElement("span", "incident-action__index", "01"));
      const actionCopy = createElement("div");
      actionCopy.append(createElement("p", "section-kicker", "Suggested next action"));
      actionCopy.append(createElement("strong", "", renderedIncident.suggested_next_action || "Review the latest evidence and owning service before taking production action."));
      action.append(actionCopy);
      if (renderedIncident.tab_target) {
        const tabLink = createElement("button", "incident-tab-link", renderedIncident.tab_target === "databases"
          ? "Open database dependencies"
          : `Open ${titleCase(renderedIncident.tab_target)}`);
        tabLink.type = "button";
        tabLink.addEventListener("click", () => setActiveTab(renderedIncident.tab_target, true));
        action.append(tabLink);
      }
      details.append(action);
      item.append(details);

      toggle.addEventListener("click", () => {
        if (model.expandedIncidents.has(incidentId)) model.expandedIncidents.delete(incidentId);
        else model.expandedIncidents.add(incidentId);
        renderIncidents(summary);
        const next = container.querySelector(`[data-incident-id="${CSS.escape(incidentId)}"] .incident__toggle`);
        if (next) next.focus({ preventScroll: true });
      });
      container.append(item);
      if (expanded && renderedIncident.kind === "domain_down" && !renderedIncident.response_excerpt) {
        void loadIncidentEvidence(renderedIncident, incidentId, summary);
      }
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

  function databaseDependenciesForDomain(domainName) {
    const dashboard = model.summary && model.summary.dashboards && model.summary.dashboards.databases || {};
    const items = Array.isArray(dashboard.items) ? dashboard.items : [];
    return items.filter((item) => Array.isArray(item.domains) && item.domains.includes(domainName));
  }

  function aggregateDatabaseStatus(items) {
    if (!items.length) return "unlinked";
    if (items.some((item) => item.telegram_alert_eligible === true)) return "down";
    if (items.some((item) => item.status === "degraded")) return "degraded";
    if (items.some((item) => item.status === "down")) return "degraded";
    if (items.every((item) => item.status === "healthy")) return "healthy";
    return "unknown";
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
    const databaseStatus = aggregateDatabaseStatus(databaseDependenciesForDomain(domain.domain));
    addCell(row, "DB", createElement(
      "span",
      `database-state-pill ${statusClass(databaseStatus)}`,
      databaseStatus === "unlinked" ? "—" : titleCase(databaseStatus)
    ));
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
      cell.colSpan = 7;
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
      cell.colSpan = 7;
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
    const linkedDatabases = databaseDependenciesForDomain(domainName);
    const databaseStatus = aggregateDatabaseStatus(linkedDatabases);
    const databaseCard = byId("selected-domain-database");
    databaseCard.className = `domain-database-card ${statusClass(databaseStatus)}`;
    databaseCard.replaceChildren();
    databaseCard.append(createElement("span", "domain-database-card__dot"));
    const databaseCopy = createElement("div");
    databaseCopy.append(createElement("strong", "", linkedDatabases.length
      ? `${formatCount(linkedDatabases.length)} database ${linkedDatabases.length === 1 ? "path" : "paths"} · ${titleCase(databaseStatus)}`
      : "No linked database dependency"));
    databaseCopy.append(createElement("small", "", linkedDatabases.length
      ? linkedDatabases.map((item) => `${item.affected_app}: ${titleCase(item.status)}`).join(" · ")
      : "This service is not yet linked to a discovered database consumer."));
    databaseCard.append(databaseCopy);
    if (linkedDatabases.length) {
      const databaseButton = createElement("button", "domain-database-card__link", "Inspect DB paths");
      databaseButton.type = "button";
      databaseButton.addEventListener("click", () => setActiveTab("databases", true));
      databaseCard.append(databaseButton);
    }
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

  function createMetricCard(label, value, detail, status = "healthy") {
    const card = createElement("article", `metric-card ${statusClass(status)}`);
    card.append(createElement("p", "metric-card__label", label));
    card.append(createElement("strong", "metric-card__value", value));
    card.append(createElement("p", "metric-card__detail", detail));
    return card;
  }

  function thresholdStatus(value, threshold) {
    const current = numberOrNull(value);
    const maximum = numberOrNull(threshold);
    if (current === null) return "unknown";
    if (maximum !== null && current >= maximum) return "critical";
    if (maximum !== null && current >= maximum * 0.85) return "attention";
    return "healthy";
  }

  function renderInfrastructureChart(host) {
    const svg = byId("chart-infrastructure");
    const samples = host && Array.isArray(host.trend_24h) ? host.trend_24h : [];
    const series = [
      { key: "cpu_used_pct", color: "#08775e", label: "CPU" },
      { key: "memory_used_pct", color: "#c0801b", label: "Memory" },
      { key: "worst_disk_used_pct", color: "#a43d37", label: "Disk" },
    ];
    const paths = [];
    if (!samples.length) {
      chartEmpty(svg, "Host trend is not yet available");
      return;
    }
    series.forEach(({ key, color, label }) => {
      const points = samples
        .map((sample, index) => {
          const value = numberOrNull(sample[key]);
          if (value === null) return null;
          return [
            samples.length === 1 ? 480 : 14 + (index / (samples.length - 1)) * 932,
            145 - (Math.max(0, Math.min(100, value)) / 100) * 126,
          ];
        })
        .filter(Boolean);
      if (points.length) {
        paths.push(createSvgElement("path", {
          d: pointsPath(points),
          fill: "none",
          stroke: color,
          "stroke-width": 2.5,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
          "vector-effect": "non-scaling-stroke",
          "aria-label": label,
        }));
      }
    });
    svg.replaceChildren(...paths);
  }

  function renderInfrastructure(summary) {
    const infrastructure = summary.dashboards && summary.dashboards.infrastructure || {};
    const host = infrastructure.host || {};
    const containers = infrastructure.containers || {};
    setStatusLabel(byId("infrastructure-status"), titleCase(infrastructure.status), infrastructure.status);
    byId("infra-host-data-state").textContent = host.data_state === "available"
      ? `Observed ${formatRelative(host.observed_at_ts, summary.generated_at_ts)}`
      : `${titleCase(host.data_state)} · ${host.observed_at_ts ? formatRelative(host.observed_at_ts, summary.generated_at_ts) : "no snapshot"}`;
    byId("infra-host-observed").textContent = host.observed_at_ts
      ? `${formatCount((host.trend_24h || []).length)} retained points · latest ${formatRelative(host.observed_at_ts, summary.generated_at_ts)}`
      : "No host observation";

    const metrics = host.metrics || {};
    const thresholds = host.thresholds || {};
    const resourceGrid = byId("infra-resource-grid");
    resourceGrid.replaceChildren(
      createMetricCard("CPU used", formatPercent(metrics.cpu_used_pct, 1), `Warn at ${formatPercent(thresholds.cpu_used_pct, 0)}`, thresholdStatus(metrics.cpu_used_pct, thresholds.cpu_used_pct)),
      createMetricCard("Memory used", formatPercent(metrics.memory_used_pct, 1), `Warn at ${formatPercent(thresholds.memory_used_pct, 0)}`, thresholdStatus(metrics.memory_used_pct, thresholds.memory_used_pct)),
      createMetricCard("Swap used", formatPercent(metrics.swap_used_pct, 1), `Warn at ${formatPercent(thresholds.swap_used_pct, 0)}`, thresholdStatus(metrics.swap_used_pct, thresholds.swap_used_pct)),
      createMetricCard("Load / CPU", numberOrNull(metrics.load1_per_cpu) === null ? "—" : Number(metrics.load1_per_cpu).toFixed(2), `${formatCount(metrics.cpu_count)} logical CPUs · warn at ${numberOrNull(thresholds.load1_per_cpu) === null ? "—" : Number(thresholds.load1_per_cpu).toFixed(2)}`, thresholdStatus(metrics.load1_per_cpu, thresholds.load1_per_cpu)),
    );
    renderInfrastructureChart(host);

    const disks = Array.isArray(host.disks) ? host.disks : [];
    const diskList = byId("infra-disk-list");
    diskList.replaceChildren();
    if (!disks.length) {
      diskList.append(createElement("p", "empty-state", "Disk capacity is not present in the latest host snapshot."));
    } else {
      disks.forEach((disk) => {
        const row = createElement("article", `disk-row ${statusClass(thresholdStatus(disk.used_percent, thresholds.disk_used_pct))}`);
        const copy = createElement("div", "disk-row__copy");
        copy.append(createElement("strong", "", disk.path || "Unnamed mount"));
        copy.append(createElement("small", "", `${formatBytes(disk.used_bytes)} used · ${formatBytes(disk.free_bytes)} free · ${formatBytes(disk.total_bytes)} total`));
        row.append(copy);
        const meter = createElement("div", "capacity-meter");
        const fill = createElement("span", "capacity-meter__fill");
        fill.style.width = `${Math.max(0, Math.min(100, numberOrNull(disk.used_percent) || 0))}%`;
        meter.append(fill);
        row.append(meter);
        row.append(createElement("strong", "disk-row__value", formatPercent(disk.used_percent, 1)));
        diskList.append(row);
      });
    }

    const counts = containers.counts || {};
    byId("container-count").textContent = formatCount(counts.total);
    byId("infra-container-data-state").textContent = containers.data_state === "available"
      ? `${formatCount(counts.healthy)} healthy · ${formatCount(counts.degraded)} degraded · collected ${formatRelative(containers.observed_at_ts, summary.generated_at_ts)}`
      : containers.data_state === "summary_only"
        ? `${formatCount(counts.total)} tracked · ${formatCount(containers.restart_total)} cumulative restarts · health pass ${formatRelative(containers.observed_at_ts, summary.generated_at_ts)}`
        : `${titleCase(containers.data_state)} · ${containers.observed_at_ts ? `last collected ${formatRelative(containers.observed_at_ts, summary.generated_at_ts)}` : "no retained container inventory"}`;
    const containerList = byId("container-list");
    containerList.replaceChildren();
    const items = Array.isArray(containers.items) ? containers.items : [];
    if (!items.length) {
      containerList.append(createElement("p", "empty-state", counts.total
        ? "The existing health pass retains aggregate restart counters and overall health, but not per-container state. Detailed rows are explicitly unavailable; the dashboard adds no Docker probe."
        : "No retained container inventory or restart counters are available. The dashboard adds no Docker probe."));
    } else {
      items.forEach((container) => {
        const row = createElement("article", `container-row ${statusClass(container.status)}`);
        const heading = createElement("div", "container-row__heading");
        heading.append(createElement("strong", "", container.name));
        heading.append(createElement("span", `status-label ${statusClass(container.status)}`, titleCase(container.status)));
        row.append(heading);
        const facts = createElement("dl", "container-row__facts");
        appendIncidentField(facts, "Docker state", container.docker_status || (container.running ? "Running" : "Unavailable"));
        appendIncidentField(facts, "Health", titleCase(container.health_status || "not reported"));
        appendIncidentField(facts, "Restarts", `${formatCount(container.restart_count)} total${numberOrNull(container.restart_increase) ? ` · +${formatCount(container.restart_increase)} this pass` : ""}`);
        appendIncidentField(facts, "Exit / OOM", `${numberOrNull(container.exit_code) === null ? "No exit code" : `Exit ${container.exit_code}`} · ${container.oom_killed ? "OOM killed" : "No OOM flag"}`);
        row.append(facts);
        if (container.error) row.append(createElement("p", "container-row__error", container.error));
        containerList.append(row);
      });
    }
  }

  function renderMiniTrend(points) {
    const wrapper = createElement("div", "availability-strip");
    (Array.isArray(points) ? points : []).forEach((point) => {
      const value = numberOrNull(point.availability_pct);
      const segment = createElement("span", "availability-strip__point");
      segment.classList.add(value === null ? "is-missing" : value >= 99.9 ? "is-healthy" : value >= 99 ? "is-attention" : "is-critical");
      segment.title = value === null ? "No observations" : `${formatPercent(value, 3)} availability`;
      wrapper.append(segment);
    });
    return wrapper;
  }

  function renderReliability(summary) {
    const reliability = summary.dashboards && summary.dashboards.reliability || {};
    const routing = reliability.routing || {};
    const groups = Array.isArray(reliability.groups) ? reliability.groups : [];
    setStatusLabel(byId("reliability-status"), titleCase(reliability.status), reliability.status);
    byId("reliability-target").textContent = numberOrNull(reliability.slo_target_pct) === null
      ? "SLO target unavailable"
      : `Default target ${formatPercent(reliability.slo_target_pct, 3)}`;
    const totalObservations = groups.reduce((sum, group) => sum + (numberOrNull(group.observations_24h) || 0), 0);
    const exhausted = groups.filter((group) => {
      const remaining = numberOrNull(group.error_budget_remaining_pct);
      return remaining !== null && remaining <= 0 && numberOrNull(group.observations_24h);
    }).length;
    byId("reliability-summary").replaceChildren(
      createMetricCard("Service groups", formatCount(groups.length), `${formatCount(totalObservations)} observations in 24 hours`, groups.length ? "healthy" : "unknown"),
      createMetricCard("Budgets exhausted", formatCount(exhausted), exhausted ? "Immediate reliability attention" : "No exhausted group budgets", exhausted ? "critical" : "healthy"),
      createMetricCard("Telegram alertable", formatCount(routing.telegram_alertable), `${formatCount(routing.enabled_services)} enabled services`, "healthy"),
      createMetricCard("Dashboard only", formatCount(routing.dashboard_only), "Explicitly suppressed from Telegram", routing.dashboard_only ? "attention" : "healthy"),
    );

    const groupList = byId("reliability-groups");
    groupList.replaceChildren();
    if (!groups.length) {
      groupList.append(createElement("p", "empty-state", "No configured service groups were available."));
    } else {
      groups.forEach((group) => {
        const row = createElement("article", `reliability-row ${statusClass(group.status)}`);
        const heading = createElement("div", "reliability-row__heading");
        const copy = createElement("div");
        copy.append(createElement("strong", "", group.label || group.id));
        copy.append(createElement("small", "", `${formatCount(group.healthy)}/${formatCount(group.services)} currently healthy · ${formatCount(group.alertable_down)} alertable · ${formatCount(group.expected_down)} dashboard only`));
        heading.append(copy);
        heading.append(createElement("span", `status-label ${statusClass(group.status)}`, titleCase(group.status)));
        row.append(heading);
        const measures = createElement("div", "reliability-row__measures");
        measures.append(createMetricCard("Availability", formatPercent(group.availability_24h_pct, 3), `${formatCount(group.observations_24h)} observations`, group.status));
        const budgetRemaining = numberOrNull(group.error_budget_remaining_pct);
        measures.append(createMetricCard("Budget remaining", formatPercent(group.error_budget_remaining_pct, 1), budgetRemaining === null ? "SLO target unavailable" : `${formatPercent(group.error_budget_consumed_pct, 1)} consumed`, budgetRemaining === null ? "unknown" : budgetRemaining <= 0 ? "critical" : "healthy"));
        measures.append(createMetricCard("HTTP p95", formatMilliseconds(group.http_p95_ms), `Browser ${formatMilliseconds(group.browser_p95_ms)}`, "healthy"));
        row.append(measures);
        const budget = createElement("div", "budget-meter");
        const budgetFill = createElement("span", "budget-meter__fill");
        budgetFill.style.width = `${Math.max(0, Math.min(100, budgetRemaining === null ? 0 : budgetRemaining))}%`;
        budget.classList.toggle("is-missing", budgetRemaining === null);
        budget.append(budgetFill);
        row.append(budget, renderMiniTrend(group.trend_24h));
        groupList.append(row);
      });
    }

    const events = Array.isArray(reliability.event_history) ? reliability.event_history : [];
    const eventList = byId("reliability-events");
    eventList.replaceChildren();
    if (!events.length) {
      eventList.append(createElement("p", "empty-state", "No incident or recovery transitions were retained in the last seven days."));
    } else {
      events.slice(0, 20).forEach((event) => {
        const row = createElement("article", `reliability-event is-${event.state || "event"}`);
        const copy = createElement("div");
        copy.append(createElement("span", "event__kind", titleCase(event.kind)));
        copy.append(createElement("strong", "", event.domain || event.owner_project || "Global monitor"));
        copy.append(createElement("p", "", event.detail || event.owner_project || "Monitor state transition"));
        row.append(copy, createElement("time", "", formatRelative(event.observed_at_ts, summary.generated_at_ts)));
        eventList.append(row);
      });
    }

    const routingList = byId("routing-summary");
    routingList.replaceChildren();
    routingList.append(
      createMetricCard("Critical route", formatCount(routing.telegram_alertable), `${routing.channel || "Telegram"} receives debounced actionable failures`, "healthy"),
      createMetricCard("Suppressed route", formatCount(routing.dashboard_only), "Still visible here; never promoted to Telegram by policy", routing.dashboard_only ? "attention" : "healthy"),
      createElement("p", "routing-note", "Routing counts are computed from the same domain policy used by the alert sender. Viewing this tab does not run checks or change suppression."),
    );
  }

  function journeyStatusLabel(status) {
    return ({ healthy: "Healthy", failing: "Failing", stale: "Stale", infra_degraded: "Infra degraded", never_run: "Never run", disabled: "Disabled", unknown: "Unavailable" })[status] || titleCase(status);
  }

  function renderJourneys(summary) {
    const journeys = summary.dashboards && summary.dashboards.journeys || {};
    const items = Array.isArray(journeys.items) ? journeys.items : [];
    setStatusLabel(byId("journeys-status"), titleCase(journeys.status), journeys.status);
    byId("journey-count").textContent = formatCount(items.length);
    byId("journey-summary").replaceChildren(
      createMetricCard("Enabled", formatCount(journeys.total), `${formatCount(journeys.disabled)} disabled`, "healthy"),
      createMetricCard("Passing", formatCount(journeys.passing), "Fresh effective journey successes", "healthy"),
      createMetricCard("Attention", formatCount((numberOrNull(journeys.failing) || 0) + (numberOrNull(journeys.stale) || 0) + (numberOrNull(journeys.infra_degraded) || 0) + (numberOrNull(journeys.never_run) || 0) + (numberOrNull(journeys.unknown) || 0)), `${formatCount(journeys.failing)} failing · ${formatCount(journeys.stale)} stale · ${formatCount(journeys.unknown)} unavailable`, journeys.status === "attention" ? "critical" : "healthy"),
      createMetricCard("Latest run", journeys.latest_run_at_ts ? formatRelative(journeys.latest_run_at_ts, summary.generated_at_ts) : "Unavailable", journeys.data_state === "available" ? "Registry-backed schedule" : titleCase(journeys.data_state), journeys.data_state === "available" ? "healthy" : "unknown"),
    );

    const list = byId("journey-list");
    list.replaceChildren();
    if (!items.length) {
      list.append(createElement("p", "empty-state", journeys.data_state === "unavailable"
        ? "The E2E registry is unavailable; journey state cannot be inferred."
        : "No E2E journeys are registered."));
      return;
    }
    const activeIds = new Set(items.map((item, index) => item.test_id || `journey-${index}`));
    [...model.expandedJourneys].forEach((id) => { if (!activeIds.has(id)) model.expandedJourneys.delete(id); });
    items.forEach((journey, index) => {
      const id = journey.test_id || `journey-${index}`;
      const panelId = `journey-details-${index}`;
      const expanded = model.expandedJourneys.has(id);
      const row = createElement("article", `journey-row ${statusClass(journey.status)}${expanded ? " is-expanded" : ""}`);
      row.dataset.journeyId = id;
      const toggle = createElement("button", "journey-row__toggle");
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-controls", panelId);
      const copy = createElement("span", "journey-row__copy");
      copy.append(createElement("strong", "", journey.test_name));
      copy.append(createElement("small", "", `${journey.owner_project || "Owner unavailable"} · ${journey.base_url || "Target unavailable"}`));
      toggle.append(copy);
      toggle.append(createElement("span", `status-label ${statusClass(journey.status)}`, journeyStatusLabel(journey.status)));
      const chevron = createSvgElement("svg", { viewBox: "0 0 20 20", "aria-hidden": "true" });
      chevron.classList.add("incident__chevron");
      chevron.append(createSvgElement("path", { d: "m5 7.5 5 5 5-5" }));
      toggle.append(chevron);
      row.append(toggle);
      const details = createElement("div", "journey-row__details");
      details.id = panelId;
      details.hidden = !expanded;
      const facts = createElement("dl", "journey-detail-grid");
      appendIncidentField(facts, "Current status", journeyStatusLabel(journey.status));
      appendIncidentField(facts, "Kind / interval", numberOrNull(journey.interval_seconds) === null
        ? `${titleCase(journey.test_kind)} · schedule unavailable`
        : `${titleCase(journey.test_kind)} · every ${formatDuration(journey.interval_seconds)}`);
      appendIncidentField(facts, "Last run", journey.last_finished_at_ts ? `${formatDateTime(journey.last_finished_at_ts)} · ${formatMilliseconds(journey.last_elapsed_ms)}` : "Never completed");
      appendIncidentField(facts, "Last success", journey.last_ok_ts ? formatDateTime(journey.last_ok_ts) : "Not retained");
      appendIncidentField(facts, "Last failure", journey.last_fail_ts ? formatDateTime(journey.last_fail_ts) : "None retained");
      appendIncidentField(facts, "Streak", `${formatCount(journey.success_streak)} success · ${formatCount(journey.fail_streak)} fail`);
      appendIncidentField(facts, "Next due", journey.next_due_ts ? formatDateTime(journey.next_due_ts) : "Scheduler time unavailable");
      appendIncidentField(facts, "Investigation", journey.investigation ? `${titleCase(journey.investigation.state)} · started ${formatRelative(journey.investigation.started_at_ts, summary.generated_at_ts)}` : "No active investigation retained");
      details.append(facts);
      const href = journey.investigation && safeDispatcherUrl(journey.investigation.url);
      if (href) {
        const link = createElement("a", "journey-investigation-link", "Open investigation");
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link);
      }
      row.append(details);
      toggle.addEventListener("click", () => {
        if (model.expandedJourneys.has(id)) model.expandedJourneys.delete(id);
        else model.expandedJourneys.add(id);
        renderJourneys(summary);
        const next = list.querySelector(`[data-journey-id="${CSS.escape(id)}"] .journey-row__toggle`);
        if (next) next.focus({ preventScroll: true });
      });
      list.append(row);
    });
  }

  function databaseMatchesQuery(item, query) {
    if (!query) return true;
    const fields = [
      item.affected_app,
      item.container,
      item.database_dependency,
      item.owner_project,
      item.failure_class,
      item.credential_state,
      item.credential_source,
      item.status,
      item.traffic_state,
      item.traffic_slot,
      item.routing_error,
      item.telegram_suppression_reason,
      ...(Array.isArray(item.domains) ? item.domains : []),
    ];
    return fields.some((value) => String(value || "").toLowerCase().includes(query));
  }

  function databaseSortValue(item) {
    if (item.telegram_alert_eligible) return -10;
    const severity = ({ down: 0, degraded: 1, healthy: 2 })[item.status] ?? 3;
    const route = ({ active: 0, unknown: 1, inactive: 2 })[item.traffic_state] ?? 3;
    return severity * 100 + route * 10 + (item.critical ? 0 : 1);
  }

  function databaseRouteLabel(item) {
    const state = titleCase(item.traffic_state || "unknown");
    const slot = item.traffic_slot ? `${titleCase(item.traffic_slot)} slot` : "Singleton route";
    const weight = numberOrNull(item.traffic_weight);
    const traffic = weight === null ? "weight unavailable" : `${weight}% traffic`;
    return `${state} · ${slot} · ${traffic}`;
  }

  function databaseAlertLabel(item) {
    if (item.telegram_alert_eligible) return "Telegram incident open";
    if (item.telegram_alert_enabled) return "Telegram armed · active critical route";
    return `Dashboard only · ${titleCase(item.telegram_suppression_reason || "policy suppressed")}`;
  }

  function appendDatabaseDomainLinks(container, domains) {
    const linked = Array.isArray(domains) ? domains : [];
    if (!linked.length) {
      container.append(createElement("span", "database-domain-link is-unlinked", "No public route linked"));
      return;
    }
    linked.forEach((domain) => {
      const button = createElement("button", "database-domain-link", domain);
      button.type = "button";
      button.addEventListener("click", () => {
        setActiveTab("domains", true);
        void selectDomain(domain);
      });
      container.append(button);
    });
  }

  function renderDatabaseRow(item, summary) {
    const row = createElement("article", `database-dependency-row ${statusClass(item.status)}`);
    const heading = createElement("div", "database-dependency-row__heading");
    const copy = createElement("div", "database-dependency-row__copy");
    const title = createElement("div", "database-dependency-row__title");
    title.append(createElement("strong", "", item.affected_app || "Unassigned app"));
    if (item.critical) title.append(createElement("span", "critical-production-tag", "Critical production"));
    if (item.traffic_state === "inactive") title.append(createElement("span", "standby-route-tag", "Standby · 0% traffic"));
    if (item.traffic_state === "unknown") title.append(createElement("span", "routing-unknown-tag", "Routing unknown"));
    copy.append(title);
    copy.append(createElement("small", "", `${item.database_dependency || "Database not named"} · ${item.container || "Container unavailable"}`));
    heading.append(copy);
    heading.append(createElement("span", `status-label ${statusClass(item.status)}`, titleCase(item.status)));
    row.append(heading);

    const facts = createElement("dl", "database-dependency-facts");
    appendIncidentField(facts, "Last success", item.last_success_at_ts
      ? `${formatDateTime(item.last_success_at_ts)} · ${formatMilliseconds(item.last_success_latency_ms)}`
      : "No successful probe retained");
    appendIncidentField(facts, "Last failure", item.last_failure_at_ts
      ? `${formatDateTime(item.last_failure_at_ts)} · ${titleCase(item.last_failure_class)} · ${formatMilliseconds(item.last_failure_latency_ms)}`
      : "No failure retained");
    appendIncidentField(facts, "Failure started", item.failure_started_at_ts
      ? `${formatDateTime(item.failure_started_at_ts)} · ${formatRelative(item.failure_started_at_ts, summary.generated_at_ts)}`
      : "No active failure");
    appendIncidentField(facts, "Current failure class", item.failure_class ? titleCase(item.failure_class) : "None");
    appendIncidentField(facts, "Credential state", titleCase(item.credential_state || "current or unproven"));
    appendIncidentField(facts, "Credential source", titleCase(item.credential_source || "unavailable"));
    appendIncidentField(facts, "Owner / project", item.owner_project || "Ownership review required");
    appendIncidentField(facts, "Production route", databaseRouteLabel(item));
    appendIncidentField(facts, "Alert route", databaseAlertLabel(item));
    row.append(facts);

    const support = createElement("div", "database-dependency-support");
    const coverage = createElement("div");
    coverage.append(createElement("p", "section-kicker", "Probe coverage"));
    coverage.append(createElement("p", "", Array.isArray(item.coverage) && item.coverage.length
      ? item.coverage.join(" · ")
      : "Coverage contract unavailable"));
    support.append(coverage);
    const routeLinks = createElement("div", "database-domain-links");
    routeLinks.append(createElement("p", "section-kicker", "Related service health"));
    appendDatabaseDomainLinks(routeLinks, item.domains);
    support.append(routeLinks);
    row.append(support);

    if (item.sanitized_error_excerpt) {
      const evidence = createElement("div", "database-failure-evidence");
      evidence.append(createElement("p", "section-kicker", "Sanitized failure evidence"));
      evidence.append(createElement("p", "", item.sanitized_error_excerpt));
      row.append(evidence);
    }
    const action = createElement("div", "database-fix-path");
    action.append(createElement("span", "database-fix-path__index", "FIX"));
    const actionCopy = createElement("div");
    actionCopy.append(createElement("p", "section-kicker", "Likely fix path"));
    actionCopy.append(createElement("strong", "", item.likely_fix_path || "Inspect the app's runtime database route and grants."));
    action.append(actionCopy);
    row.append(action);
    const observed = createElement("time", "database-dependency-row__observed", `Observed ${formatRelative(item.observed_at_ts, summary.generated_at_ts)}`);
    if (item.observed_at_ts) observed.dateTime = new Date(Number(item.observed_at_ts) * 1000).toISOString();
    row.append(observed);
    return row;
  }

  function renderDatabases(summary) {
    const databases = summary.dashboards && summary.dashboards.databases || {};
    const allItems = Array.isArray(databases.items) ? databases.items : [];
    const query = byId("database-filter").value.trim().toLowerCase();
    const items = allItems
      .filter((item) => databaseMatchesQuery(item, query))
      .sort((left, right) => databaseSortValue(left) - databaseSortValue(right)
        || String(left.affected_app || "").localeCompare(String(right.affected_app || "")));
    setStatusLabel(byId("databases-status"), titleCase(databases.status), databases.status);
    byId("database-summary").replaceChildren(
      createMetricCard("Dependencies", formatCount(databases.total), `${formatCount(databases.healthy)} healthy`, databases.total ? "healthy" : "unknown"),
      createMetricCard("Attention", formatCount(databases.degraded), `${formatCount(databases.standby_degraded)} standby · ${formatCount(databases.down)} down`, databases.degraded ? "attention" : "healthy"),
      createMetricCard("Alertable down", formatCount(databases.alertable_down), `${formatCount(databases.open_alert_groups)} open alert groups`, databases.alertable_down ? "critical" : "healthy"),
      createMetricCard("Collector state", titleCase(databases.data_state), databases.generated_at_ts
        ? `${databases.collector_error_class ? `${titleCase(databases.collector_error_class)} · ` : ""}updated ${formatRelative(databases.generated_at_ts, summary.generated_at_ts)}`
        : "No state file yet", databases.data_state === "live" ? "healthy" : "unknown"),
    );
    const list = byId("database-dependency-list");
    list.replaceChildren();
    if (!items.length) {
      const message = query
        ? "No database dependencies match this filter."
        : ({
          missing: "The database sidecar has not written its first compact state file yet.",
          invalid: "The database state file is invalid; inspect the collector contract.",
          unreadable: "The database state file is unreadable; inspect the state-volume boundary.",
        })[databases.data_state] || "No database-backed production app containers were discovered.";
      list.append(createElement("p", "empty-state", message));
      return;
    }
    items.forEach((item) => list.append(renderDatabaseRow(item, summary)));
  }

  function setActiveTab(name, focus = false) {
    const tabs = [...document.querySelectorAll("[data-dashboard-tab]")];
    if (!tabs.some((tab) => tab.dataset.dashboardTab === name)) return;
    model.activeTab = name;
    tabs.forEach((tab) => {
      const selected = tab.dataset.dashboardTab === name;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    document.querySelectorAll("[data-dashboard-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.dashboardPanel !== name;
    });
    window.history.replaceState(null, "", `#${name}`);
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
    renderInfrastructure(summary);
    renderReliability(summary);
    renderJourneys(summary);
    renderDatabases(summary);
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
    byId("database-filter").addEventListener("input", () => {
      if (model.summary) renderDatabases(model.summary);
    });
    const tabs = [...document.querySelectorAll("[data-dashboard-tab]")];
    const requestedTab = window.location.hash.replace(/^#/, "");
    if (tabs.some((tab) => tab.dataset.dashboardTab === requestedTab)) model.activeTab = requestedTab;
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => setActiveTab(tab.dataset.dashboardTab, false));
      tab.addEventListener("keydown", (event) => {
        let nextIndex = null;
        if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
        if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
        if (event.key === "Home") nextIndex = 0;
        if (event.key === "End") nextIndex = tabs.length - 1;
        if (nextIndex === null) return;
        event.preventDefault();
        setActiveTab(tabs[nextIndex].dataset.dashboardTab, true);
      });
    });
    setActiveTab(model.activeTab);
    loadDashboard();
  });
})();
