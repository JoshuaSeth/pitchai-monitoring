(function () {
  "use strict";

  const state = {
    snapshot: null,
    zone: "utc",
    historySeries: "combined",
    bankExpanded: false,
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

  const riskLabels = {
    low: "Low risk",
    medium: "Medium risk",
    high: "High risk",
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

  function compactNumber(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return "-";
    return new Intl.NumberFormat(undefined, {
      notation: parsed >= 10_000 ? "compact" : "standard",
      maximumFractionDigits: parsed >= 10_000 ? 1 : 0,
    }).format(parsed);
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
    if (Math.abs(value) <= 1) return "now";
    const future = value > 0;
    const absolute = Math.abs(value);
    const phrase = (duration) => future ? `in ${duration}` : `${duration} ago`;
    if (absolute < 60) return phrase(`${Math.ceil(absolute)}s`);
    const minutes = Math.ceil(absolute / 60);
    if (minutes < 60) return phrase(`${minutes}m`);
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    if (hours < 24) return phrase(remainder ? `${hours}h ${remainder}m` : `${hours}h`);
    const days = Math.floor(hours / 24);
    const dayHours = hours % 24;
    return phrase(dayHours ? `${days}d ${dayHours}h` : `${days}d`);
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

  function svgElement(tag, className, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    if (className) node.setAttribute("class", className);
    for (const [name, value] of Object.entries(attributes || {})) {
      node.setAttribute(name, String(value));
    }
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
        mobileField("Banked resets", creditsCell(account)),
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

  function renderRunout(forecast) {
    const payload = forecast || {};
    const burn = payload.burn_rate || {};
    const sourceLabel = burn.source === "native_broker_samples"
      ? `trailing ${burn.lookback_hours || 2}h observed`
      : "current-window estimate";
    byId("burn-rate").textContent = `${number(burn.capacity_points_per_hour, 1) || "0.0"} points/hour · ${sourceLabel} · ${burn.confidence || "low"} confidence`;

    const cells = [];
    for (const horizon of payload.horizons || []) {
      const risk = riskLabels[horizon.risk] ? horizon.risk : "low";
      const cell = element("article", `runout-cell risk-${risk}`);
      const head = element("div", "runout-cell-head");
      head.append(
        element("span", "runout-horizon", horizon.label),
        element("span", `risk-badge ${risk}`, riskLabels[risk])
      );
      const probability = element("div", "runout-probability");
      probability.append(
        element("strong", "", number(horizon.probability_percent, 0) || "0"),
        element("span", "", "%")
      );
      const meterRoot = element("div", `risk-meter ${risk}`);
      const meterFill = document.createElement("span");
      meterFill.style.setProperty("--value", `${Math.max(0, Math.min(100, Number(horizon.probability_percent) || 0))}%`);
      meterRoot.appendChild(meterFill);
      let timing = "No likely runout in this window";
      if (horizon.likely_window_start && horizon.likely_window_end) {
        timing = `${formatTime(horizon.likely_window_start, false)} to ${formatTime(horizon.likely_window_end, false)}`;
      } else if (horizon.expected_runout_at) {
        timing = `Expected near ${formatTime(horizon.expected_runout_at, false)}`;
      }
      const detail = element("div", "runout-detail");
      detail.append(
        element("span", "", `${number(horizon.initial_capacity_points, 0) || "0"} points now`),
        element("span", "", `${horizon.scheduled_five_hour_resets || 0} automatic resets`)
      );
      cell.append(
        head,
        probability,
        meterRoot,
        element("div", "runout-timing", timing),
        detail
      );
      cells.push(cell);
    }
    setChildren(byId("runout-grid"), cells);

    const drivers = (payload.drivers || []).map((driver) => {
      const item = element("span", "runout-driver");
      item.append(element("i", "", ""), document.createTextNode(driver));
      return item;
    });
    setChildren(byId("runout-drivers"), drivers);
  }

  function niceMaximum(value) {
    const maximum = Math.max(1, Number(value) || 0);
    const magnitude = 10 ** Math.floor(Math.log10(maximum));
    const normalized = maximum / magnitude;
    const rounded = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
    return rounded * magnitude;
  }

  function shortHour(value, includeHour) {
    const parsed = parseDate(value);
    if (!parsed) return "-";
    const options = {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    };
    if (includeHour) {
      options.hour = "2-digit";
      options.hour12 = false;
    }
    return new Intl.DateTimeFormat(undefined, options).format(parsed);
  }

  function smoothLinePath(coordinates) {
    if (!coordinates.length) return "";
    if (coordinates.length === 1) return `M${coordinates[0][0]},${coordinates[0][1]}`;
    let path = `M${coordinates[0][0].toFixed(2)},${coordinates[0][1].toFixed(2)}`;
    for (let index = 1; index < coordinates.length - 1; index += 1) {
      const point = coordinates[index];
      const next = coordinates[index + 1];
      const midpoint = [(point[0] + next[0]) / 2, (point[1] + next[1]) / 2];
      path += ` Q${point[0].toFixed(2)},${point[1].toFixed(2)} ${midpoint[0].toFixed(2)},${midpoint[1].toFixed(2)}`;
    }
    const last = coordinates[coordinates.length - 1];
    path += ` L${last[0].toFixed(2)},${last[1].toFixed(2)}`;
    return path;
  }

  function renderLineChart(points, seriesLabel, hasCoverage) {
    const frame = byId("usage-chart");
    if (!hasCoverage || !Array.isArray(points) || !points.length) {
      setChildren(frame, [element("div", "chart-empty", "Token history is not available yet.")]);
      return;
    }

    const compact = window.innerWidth < 620;
    const width = compact ? 420 : 1440;
    const height = compact ? 300 : 390;
    const padding = { top: 22, right: 24, bottom: 48, left: compact ? 62 : 76 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const values = points.map((point) => Math.max(0, Number(point.smoothed_tokens ?? point.tokens) || 0));
    const yMaximum = niceMaximum(Math.max(...values));
    const xFor = (index) => padding.left + (points.length === 1 ? plotWidth / 2 : index * plotWidth / (points.length - 1));
    const yFor = (value) => padding.top + plotHeight - value / yMaximum * plotHeight;

    const svg = svgElement("svg", "usage-line-chart", {
      viewBox: `0 0 ${width} ${height}`,
      "aria-hidden": "true",
      focusable: "false",
    });
    for (let index = 0; index <= 4; index += 1) {
      const value = yMaximum * (4 - index) / 4;
      const y = padding.top + plotHeight * index / 4;
      svg.appendChild(svgElement("line", "chart-grid-line", {
        x1: padding.left,
        x2: width - padding.right,
        y1: y,
        y2: y,
      }));
      const label = svgElement("text", "chart-y-label", { x: padding.left - 11, y: y + 4, "text-anchor": "end" });
      label.textContent = compactNumber(value);
      svg.appendChild(label);
    }

    const coordinates = values.map((value, index) => [xFor(index), yFor(value)]);
    const linePath = smoothLinePath(coordinates);
    const areaPath = `${linePath} L${coordinates[coordinates.length - 1][0].toFixed(2)},${(padding.top + plotHeight).toFixed(2)} L${coordinates[0][0].toFixed(2)},${(padding.top + plotHeight).toFixed(2)} Z`;
    svg.appendChild(svgElement("path", "chart-area", { d: areaPath }));
    svg.appendChild(svgElement("path", "chart-line", { d: linePath }));

    const tickEvery = compact ? 48 : 24;
    points.forEach((point, index) => {
      if (index % tickEvery === 0 || index === points.length - 1) {
        const xLabel = svgElement("text", "chart-x-label", {
          x: coordinates[index][0],
          y: height - 14,
          "text-anchor": index === 0 ? "start" : index === points.length - 1 ? "end" : "middle",
        });
        xLabel.textContent = shortHour(point.at, index === points.length - 1);
        svg.appendChild(xLabel);
      }
      if (point.provenance === "observed" || point.provenance === "blended" || index === points.length - 1) {
        const marker = svgElement("circle", `chart-point ${point.provenance || ""}`, {
          cx: coordinates[index][0],
          cy: coordinates[index][1],
          r: point.provenance === "observed" ? 3.5 : 2.5,
        });
        const title = svgElement("title", "", {});
        title.textContent = `${seriesLabel}: ${compactNumber(point.tokens)} tokens · ${shortHour(point.at, true)} UTC · ${point.provenance || "estimated"}`;
        marker.appendChild(title);
        svg.appendChild(marker);
      }
    });
    frame.setAttribute("aria-label", `${seriesLabel} smoothed hourly token usage over the past seven days`);
    setChildren(frame, [svg]);
  }

  function renderHistory(history) {
    const payload = history || {};
    const series = Array.isArray(payload.series) ? payload.series : [];
    const select = byId("history-series");
    const options = [element("option", "", "All accounts combined")];
    options[0].value = "combined";
    for (const item of series) {
      const option = element("option", "", item.label);
      option.value = item.label;
      options.push(option);
    }
    if (state.historySeries !== "combined" && !series.some((item) => item.label === state.historySeries)) {
      state.historySeries = "combined";
    }
    setChildren(select, options);
    select.value = state.historySeries;

    const selected = state.historySeries === "combined"
      ? null
      : series.find((item) => item.label === state.historySeries);
    const points = selected ? selected.points : payload.combined;
    const values = Array.isArray(points) ? points.map((point) => Number(point.tokens) || 0) : [];
    const total = values.reduce((sum, value) => sum + value, 0);
    const summary = selected ? {
      seven_day_tokens: total,
      average_hourly_tokens: values.length ? Math.round(total / values.length) : 0,
      peak_hourly_tokens: values.length ? Math.max(...values) : 0,
      trailing_two_hour_tokens: values.slice(-2).reduce((sum, value) => sum + value, 0),
      observed_share_percent: total
        ? Math.round(points.reduce((sum, point) => sum + Number(point.observed_tokens || 0), 0) / total * 1000) / 10
        : 0,
    } : payload.summary || {};
    const stats = [
      ["Seven days", compactNumber(summary.seven_day_tokens), "tokens"],
      ["Hourly average", compactNumber(summary.average_hourly_tokens), "tokens / hour"],
      ["Peak hour", compactNumber(summary.peak_hourly_tokens), "tokens"],
      ["Trailing 2h", compactNumber(summary.trailing_two_hour_tokens), "tokens"],
    ].map(([label, value, unit]) => {
      const item = element("div", "history-stat");
      item.append(
        element("span", "history-stat-label", label),
        element("strong", "", value),
        element("small", "", unit)
      );
      return item;
    });
    setChildren(byId("history-stats"), stats);
    const coverage = Number(payload.accounts_reporting || 0);
    const configured = Number(payload.configured_accounts || 0);
    const updatedAt = selected ? selected.updated_at : payload.updated_at;
    const nativeHours = selected ? Number(selected.native_hour_count || 0) : Number(payload.reconstruction?.native_hour_count || 0);
    byId("history-freshness").textContent = `${coverage}/${configured} accounts · ${updatedAt ? ageFromIso(updatedAt) : "pending"}`;
    byId("history-method").textContent = "Provider daily totals · hourly UTC reconstruction · 3-hour smooth";
    byId("history-coverage").textContent = nativeHours
      ? `${nativeHours} hour${nativeHours === 1 ? "" : "s"} include observed deltas`
      : "Estimated hourly shape; native coverage is accumulating";
    renderLineChart(points || [], selected ? selected.label : "All accounts combined", coverage > 0);
  }

  function renderResetBank(bank) {
    const payload = bank || {};
    const total = payload.total_available;
    byId("reset-bank-count").textContent = total === null || total === undefined ? "-" : String(total);
    const details = Array.isArray(payload.details) ? payload.details : [];
    const visibleDetails = state.bankExpanded ? details : details.slice(0, 6);
    const rows = [];
    for (const detail of visibleDetails) {
      const row = element("article", "reset-bank-row");
      const identity = element("div", "reset-bank-account");
      identity.dataset.label = "Account";
      identity.appendChild(element("strong", "", detail.account_label));
      if (detail.status) identity.appendChild(element("span", "", detail.status));
      const reset = element("div", "reset-bank-kind");
      reset.dataset.label = "Reset";
      reset.append(
        element("strong", "", detail.title || detail.reset_type || "Usage reset"),
        element("span", "", detail.reset_type || "Unspecified")
      );
      const granted = element("div", "reset-bank-date");
      granted.dataset.label = "Granted";
      granted.appendChild(element("strong", "", formatTime(detail.granted_at, false)));
      const expires = element("div", "reset-bank-date");
      expires.dataset.label = "Expires";
      expires.append(
        element("strong", "", formatTime(detail.expires_at, false)),
        element("span", detail.expires_in_seconds < 0 ? "is-expired" : "", formatDuration(detail.expires_in_seconds))
      );
      row.append(identity, reset, granted, expires);
      rows.push(row);
    }
    if (!rows.length) {
      const message = Number(total) > 0
        ? `${total} banked reset${Number(total) === 1 ? "" : "s"}; dated detail is unavailable.`
        : "No banked usage resets are currently available.";
      rows.push(element("div", "empty-state", message));
    }
    setChildren(byId("reset-bank-list"), rows);
    const toggle = byId("reset-bank-toggle");
    toggle.hidden = details.length <= 6;
    toggle.textContent = state.bankExpanded
      ? "Show next six resets"
      : `Show all ${details.length} resets`;
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
    renderRunout(snapshot.runout_forecast || {});
    renderForecasts(snapshot.forecasts || []);
    renderHistory(snapshot.usage_history || {});
    renderResetBank(snapshot.reset_bank || {});
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
    byId("history-series").addEventListener("change", (event) => {
      state.historySeries = event.target.value || "combined";
      if (state.snapshot) renderHistory(state.snapshot.usage_history || {});
    });
    byId("reset-bank-toggle").addEventListener("click", () => {
      state.bankExpanded = !state.bankExpanded;
      if (state.snapshot) renderResetBank(state.snapshot.reset_bank || {});
    });
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
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      if (resizeTimer) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        if (state.snapshot) renderHistory(state.snapshot.usage_history || {});
      }, 120);
    });
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
