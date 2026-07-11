(function () {
  "use strict";

  const state = {
    snapshot: null,
    zone: "utc",
    toastTimer: null,
  };

  const statusLabels = {
    available: "Available",
    five_hour_limited: "5h limited",
    weekly_limited: "Weekly limited",
    auth_invalid: "Auth invalid",
    disabled: "Disabled",
    unknown: "Unknown",
  };

  const eventLabels = {
    five_hour_reset: "5-hour reset",
    weekly_reset: "Weekly reset",
    reset_credit_expiry: "Reset credit expiry",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function text(value) {
    return value === null || value === undefined || value === "" ? "-" : String(value);
  }

  function number(value, digits) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return null;
    return parsed.toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function parseDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date : null;
  }

  function formatTime(value, includeSeconds) {
    const date = parseDate(value);
    if (!date) return "Unknown";
    const options = {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: state.zone === "utc" ? "UTC" : undefined,
      timeZoneName: "short",
    };
    if (includeSeconds) options.second = "2-digit";
    return new Intl.DateTimeFormat(undefined, options).format(date);
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value)) return "Unknown";
    if (value <= 1) return "now";
    if (value < 60) return `in ${Math.ceil(value)}s`;
    const minutes = Math.ceil(value / 60);
    if (minutes < 60) return `in ${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    if (hours < 24) return remainder ? `in ${hours}h ${remainder}m` : `in ${hours}h`;
    const days = Math.floor(hours / 24);
    const dayHours = hours % 24;
    return dayHours ? `in ${days}d ${dayHours}h` : `in ${days}d`;
  }

  function ageFromIso(value) {
    const date = parseDate(value);
    if (!date) return "Never";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  function setChildren(parent, children) {
    parent.replaceChildren(...children.filter(Boolean));
  }

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = text(value);
    return node;
  }

  function meter(value, className) {
    const parsed = Math.max(0, Math.min(100, Number(value) || 0));
    const root = element("div", className || "capacity-meter");
    if (parsed <= 10) root.classList.add("is-low");
    else if (parsed <= 35) root.classList.add("is-mid");
    const fill = document.createElement("span");
    fill.style.setProperty("--value", `${parsed}%`);
    root.appendChild(fill);
    return root;
  }

  function statusBadge(status) {
    const badge = element("span", `status-badge ${status}`, statusLabels[status] || status);
    return badge;
  }

  function capacityCell(window) {
    const wrapper = document.createElement("div");
    const remaining = window && window.remaining_percent;
    const used = window && window.used_percent;
    if (!Number.isFinite(Number(remaining))) {
      wrapper.appendChild(element("span", "cell-sub", "Not measured"));
      return wrapper;
    }
    const line = element("div", "capacity-number");
    const strong = element("strong", "", `${number(remaining, 0)}% left`);
    const usedNode = element("span", "", `${number(used, 0)}% used`);
    line.append(strong, usedNode);
    wrapper.append(line, meter(remaining, "capacity-meter"));
    return wrapper;
  }

  function resetCell(window) {
    const wrapper = document.createElement("div");
    if (!window || !window.reset_at) {
      wrapper.appendChild(element("div", "reset-time", "Unknown"));
      return wrapper;
    }
    wrapper.append(
      element("div", "reset-time", formatTime(window.reset_at, false)),
      element("div", "reset-relative", formatDuration(window.reset_in_seconds))
    );
    return wrapper;
  }

  function creditsCell(account) {
    const wrapper = document.createElement("div");
    const credits = account.reset_credits || {};
    const count = credits.available_count;
    const countNode = element("div", "credits-count", count === null || count === undefined ? "Unknown" : `${count} banked`);
    if (Number(count) > 0) countNode.classList.add("has-credits");
    wrapper.appendChild(countNode);
    const details = Array.isArray(credits.details) ? credits.details : [];
    if (details.length) {
      for (const detail of details) {
        if (!detail.expires_at && !detail.granted_at) continue;
        const label = detail.expires_at
          ? `Expires ${formatTime(detail.expires_at, false)}`
          : `Granted ${formatTime(detail.granted_at, false)}`;
        wrapper.appendChild(element("div", "credit-date", label));
      }
      if (details.length < Number(count || 0)) {
        wrapper.appendChild(element("div", "cell-sub", `${details.length} dated detail row(s)`));
      }
    } else if (Number(count) > 0) {
      wrapper.appendChild(element("div", "cell-sub", "Provider returned count only"));
    }
    return wrapper;
  }

  function freshnessCell(account) {
    const wrapper = document.createElement("div");
    const age = element("div", `freshness${account.stale ? " is-stale" : ""}`, ageFromIso(account.last_probe_at));
    wrapper.appendChild(age);
    if (account.probe_error) wrapper.appendChild(element("div", "cell-sub", "Probe failed"));
    if (Number(account.active_session_count) > 0) {
      wrapper.appendChild(element("div", "session-note", `${account.active_session_count} active user session${account.active_session_count === 1 ? "" : "s"}`));
    }
    return wrapper;
  }

  function accountIdentity(account) {
    const wrapper = document.createElement("div");
    wrapper.appendChild(element("div", "account-name", account.label));
    if (account.email && account.email !== account.label) {
      wrapper.appendChild(element("div", "account-alias", account.email));
    }
    return wrapper;
  }

  function renderAccountTable(accounts) {
    const rows = [];
    for (const account of accounts) {
      const row = document.createElement("tr");
      const values = [
        accountIdentity(account),
        statusBadge(account.status),
        capacityCell(account.five_hour),
        resetCell(account.five_hour),
        capacityCell(account.weekly),
        resetCell(account.weekly),
        creditsCell(account),
        freshnessCell(account),
      ];
      for (const value of values) {
        const cell = document.createElement("td");
        cell.appendChild(value);
        row.appendChild(cell);
      }
      rows.push(row);
    }
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = element("td", "empty-state", "No broker accounts are available in the current snapshot.");
      cell.colSpan = 8;
      row.appendChild(cell);
      rows.push(row);
    }
    setChildren(byId("account-table-body"), rows);
  }

  function mobileField(label, content) {
    const field = document.createElement("div");
    field.append(element("div", "mobile-field-label", label), content);
    return field;
  }

  function renderMobileAccounts(accounts) {
    const cards = [];
    for (const account of accounts) {
      const card = element("article", "mobile-account");
      const header = element("div", "mobile-account-header");
      header.append(accountIdentity(account), statusBadge(account.status));
      const grid = element("div", "mobile-account-grid");
      grid.append(
        mobileField("5-hour capacity", capacityCell(account.five_hour)),
        mobileField("5-hour reset", resetCell(account.five_hour)),
        mobileField("Weekly capacity", capacityCell(account.weekly)),
        mobileField("Weekly reset", resetCell(account.weekly)),
        mobileField("Redeemable resets", creditsCell(account)),
        mobileField("Freshness", freshnessCell(account))
      );
      card.append(header, grid);
      cards.push(card);
    }
    if (!cards.length) cards.push(element("div", "empty-state", "No broker accounts in this snapshot."));
    setChildren(byId("mobile-account-list"), cards);
  }

  function renderForecasts(forecasts) {
    const cells = [];
    for (const forecast of forecasts || []) {
      const cell = element("article", "forecast-cell");
      const value = element("div", "forecast-value");
      value.append(element("span", "", number(forecast.capacity_percent, 1) || "0.0"), element("small", "", "%"));
      const detail = element("div", "forecast-detail");
      detail.append(
        element("span", "", `${number(forecast.capacity_points, 0) || "0"} points`),
        element("span", "", `${number(forecast.account_equivalents, 2) || "0"} account windows`)
      );
      const secondary = element("div", "forecast-detail");
      secondary.append(
        element("span", "", `${forecast.contributing_accounts || 0} contributors`),
        element("span", "", `${forecast.five_hour_resets || 0} resets`)
      );
      cell.append(
        element("div", "forecast-label", forecast.label),
        value,
        meter(forecast.capacity_percent, "forecast-meter"),
        detail,
        secondary
      );
      cells.push(cell);
    }
    setChildren(byId("forecast-grid"), cells);
  }

  function renderWarnings(warnings) {
    const section = byId("warning-section");
    const items = [];
    for (const warning of warnings || []) {
      const item = element("div", `warning-item${warning.severity === "critical" ? " is-critical" : ""}`);
      if (warning.account_label) {
        item.append(element("span", "warning-account", warning.account_label), document.createTextNode(" - "));
      }
      item.appendChild(document.createTextNode(warning.message || warning.code || "Attention required"));
      items.push(item);
    }
    section.classList.toggle("is-empty", items.length === 0);
    setChildren(byId("warning-list"), items);
  }

  function renderEvents(events) {
    const items = [];
    for (const event of (events || []).slice(0, 18)) {
      const item = element("article", "event-item");
      item.append(
        element("div", "event-kind", eventLabels[event.kind] || event.kind),
        element("div", "event-account", event.account_label),
        element("div", "event-time", `${formatTime(event.at, false)} · ${formatDuration(event.in_seconds)}`)
      );
      items.push(item);
    }
    if (!items.length) items.push(element("div", "empty-state", "No useful capacity reset is scheduled in the next 24 hours."));
    setChildren(byId("event-list"), items);
  }

  function renderDecision(snapshot) {
    const summary = snapshot.summary || {};
    const usable = Number(summary.usable_now || 0);
    const band = document.querySelector(".decision-band");
    band.classList.remove("is-warning", "is-critical");
    byId("usable-count").textContent = String(usable);
    if (usable >= 3) {
      byId("decision-title").textContent = `${usable} accounts are ready for concurrent work`;
      byId("decision-detail").textContent = "Capacity is distributed across multiple auth-valid accounts. Continue to preserve accounts with the lowest five-hour headroom.";
    } else if (usable === 2) {
      band.classList.add("is-warning");
      byId("decision-title").textContent = "Two accounts are selectable now";
      byId("decision-detail").textContent = "Normal work fits, but sustained multi-agent load should be paced against the next five-hour reset.";
    } else if (usable === 1) {
      band.classList.add("is-critical");
      byId("decision-title").textContent = "Only one account is selectable now";
      byId("decision-detail").textContent = "Avoid bursty manager and subagent workloads until another five-hour window resets.";
    } else {
      band.classList.add("is-critical");
      byId("decision-title").textContent = "No account is currently selectable";
      byId("decision-detail").textContent = "Wait for the next eligible reset or repair accounts flagged as auth invalid.";
    }
    byId("next-capacity").textContent = summary.next_useful_capacity_at
      ? `Next useful reset: ${summary.next_useful_capacity_label} · ${formatTime(summary.next_useful_capacity_at, false)}`
      : "No useful reset inside 24 hours";
  }

  function renderLiveState(snapshot) {
    const source = snapshot.source || {};
    const dot = byId("live-dot");
    dot.className = "live-dot";
    if (source.error) {
      dot.classList.add("is-critical");
      byId("live-title").textContent = "Broker refresh failed";
    } else if (source.stale) {
      dot.classList.add("is-warning");
      byId("live-title").textContent = "Broker data needs attention";
    } else {
      dot.classList.add("is-good");
      byId("live-title").textContent = "Live broker state";
    }
    byId("generated-at").textContent = `Rendered ${formatTime(snapshot.generated_at, true)}`;
    byId("probe-age").textContent = source.last_safe_probe_at
      ? `Usage probe ${ageFromIso(source.last_safe_probe_at)}`
      : "Usage probe pending";
  }

  function render(snapshot) {
    state.snapshot = snapshot;
    renderLiveState(snapshot);
    renderDecision(snapshot);
    renderForecasts(snapshot.forecasts || []);
    renderWarnings(snapshot.warnings || []);
    renderAccountTable(snapshot.accounts || []);
    renderMobileAccounts(snapshot.accounts || []);
    renderEvents(snapshot.events || []);
    const methodology = snapshot.methodology || {};
    if (methodology.definition) {
      byId("method-note").textContent = `${methodology.definition} ${methodology.weekly_handling || ""}`.trim();
    }
  }

  async function loadSnapshot(options) {
    const opts = options || {};
    const response = await fetch("/api/v1/capacity", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error(`capacity_http_${response.status}`);
    const snapshot = await response.json();
    render(snapshot);
    if (opts.toast) showToast("Broker snapshot updated");
  }

  async function requestRefresh() {
    const button = byId("refresh-button");
    button.disabled = true;
    button.classList.add("is-spinning");
    try {
      const response = await fetch("/api/v1/refresh", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Auth-Usage-Action": "refresh" },
      });
      if (!response.ok) throw new Error(`refresh_http_${response.status}`);
      const payload = await response.json();
      render(payload.snapshot);
      if (payload.probe_started) showToast("Safe usage probe completed");
      else if (payload.reason === "probe_throttled") showToast(`Probe is fresh; retry in ${payload.retry_after_seconds}s`);
      else showToast("Snapshot refreshed without probing");
    } catch (error) {
      showToast("Refresh failed; current snapshot retained");
    } finally {
      button.disabled = false;
      button.classList.remove("is-spinning");
    }
  }

  function showToast(message) {
    const toast = byId("toast");
    toast.textContent = message;
    toast.classList.add("is-visible");
    if (state.toastTimer) window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
  }

  function setZone(zone) {
    state.zone = zone === "local" ? "local" : "utc";
    for (const button of document.querySelectorAll(".zone-option")) {
      button.classList.toggle("is-active", button.dataset.zone === state.zone);
    }
    if (state.snapshot) render(state.snapshot);
  }

  function initialize() {
    byId("refresh-button").addEventListener("click", requestRefresh);
    for (const button of document.querySelectorAll(".zone-option")) {
      button.addEventListener("click", () => setZone(button.dataset.zone));
    }
    loadSnapshot().catch(() => {
      byId("live-dot").className = "live-dot is-critical";
      byId("live-title").textContent = "Dashboard data unavailable";
      byId("decision-title").textContent = "Could not load the broker snapshot";
      byId("decision-detail").textContent = "The service is reachable, but its protected capacity API did not return current data.";
      showToast("Unable to load broker capacity");
    });
    window.setInterval(() => loadSnapshot().catch(() => {}), 30_000);
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
