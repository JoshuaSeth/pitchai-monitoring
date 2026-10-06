(function () {
  "use strict";

  // OpenCode Go subscriptions of the isolated bridge's rotating keyring: one card per
  // subscription with its rolling 5-hour, weekly and monthly windows and the bridge state.
  const REFRESH_MS = 60_000;
  const STATUS = {
    ready: { label: "Ready", badge: "available" },
    limited: { label: "Limit reached", badge: "weekly_limited" },
    cooldown: { label: "Bridge cooldown", badge: "five_hour_limited" },
    auth_invalid: { label: "Key rejected", badge: "auth_invalid" },
    unavailable: { label: "Status unavailable", badge: "unknown" },
  };
  const WINDOWS = [["rolling", "5-hour window"], ["weekly", "Weekly window"], ["monthly", "Monthly window"]];
  const view = { payload: null, error: null };

  function byId(id) {
    return document.getElementById(id);
  }

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }

  function finite(value) {
    if (value === null || value === undefined || typeof value === "boolean") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function zone() {
    const active = document.querySelector(".zone-option.is-active");
    return active && active.dataset.zone === "local" ? undefined : "UTC";
  }

  function when(value) {
    const date = value ? new Date(value) : null;
    if (!date || !Number.isFinite(date.getTime())) return null;
    const stamp = date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: zone(), timeZoneName: "short" });
    return `${stamp} · ${relative(date)}`;
  }

  function relative(date) {
    const seconds = (date.getTime() - Date.now()) / 1000;
    const absolute = Math.abs(seconds);
    const phrase = (text) => (seconds >= 0 ? `in ${text}` : `${text} ago`);
    if (absolute < 3600) return phrase(`${Math.max(1, Math.round(absolute / 60))}m`);
    if (absolute < 172800) return phrase(`${Math.round(absolute / 3600)}h`);
    return phrase(`${Math.round(absolute / 86400)}d`);
  }

  function age(value) {
    const date = value ? new Date(value) : null;
    if (!date || !Number.isFinite(date.getTime())) return "never";
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    if (seconds < 60) return `${Math.floor(seconds)}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    return `${Math.floor(seconds / 3600)}h ago`;
  }

  function meter(remaining) {
    const root = element("div", "capacity-meter");
    const value = Math.max(0, Math.min(100, remaining === null ? 0 : remaining));
    if (remaining === null) root.classList.add("is-unavailable");
    if (value <= 10) root.classList.add("is-low");
    else if (value <= 35) root.classList.add("is-mid");
    const fill = document.createElement("span");
    fill.style.setProperty("--value", `${value}%`);
    root.appendChild(fill);
    return root;
  }

  function windowMeter(label, reading) {
    const wrapper = element("div", "claude-window");
    wrapper.appendChild(element("div", "claude-window-label", label));
    const used = reading ? finite(reading.used_percent) : null;
    if (used === null) {
      wrapper.appendChild(element("div", "claude-window-reset", "Not reported"));
      return wrapper;
    }
    const remaining = finite(reading.remaining_percent) ?? Math.max(0, 100 - used);
    const line = element("div", "capacity-number");
    line.append(element("strong", "", `${Math.round(remaining)}% left`), element("span", "", `${Math.round(used)}% used`));
    const reset = when(reading.reset_at);
    const limited = used >= 100 || reading.status === "rate-limited";
    const resetText = limited ? `Limit reached · ${reset ? `resets ${reset}` : "no reset reported"}` : reset ? `Resets ${reset}` : "No reset reported";
    wrapper.append(line, meter(remaining), element("div", `claude-window-reset${limited ? " is-limited" : ""}`, resetText));
    return wrapper;
  }

  function card(account) {
    const status = STATUS[account.status] || STATUS.unavailable;
    const root = element("article", "claude-account opencode-account");
    const heading = element("div", "claude-account-heading");
    heading.append(element("h3", "", account.label), element("span", `status-badge ${status.badge}`, status.label));
    const bridge = finite(account.bridge_last_status);
    root.append(heading, element("p", "claude-account-meta", [
      "OpenCode Go",
      `rotation slot ${account.position}`,
      bridge === null ? "no bridge result yet" : `last bridge result HTTP ${bridge}`,
    ].join(" · ")));
    const windows = account.windows || {};
    const meters = element("div", "claude-windows opencode-windows");
    meters.append(...WINDOWS.map(([key, label]) => windowMeter(label, windows[key])));
    root.append(meters);
    const notes = [];
    const available = when(account.available_at);
    if (account.status !== "ready" && available) notes.push(`Usable again ${available}`);
    const cooldown = when(account.bridge_cooldown_until);
    if (cooldown) notes.push(`Bridge holds this key until ${cooldown}`);
    if (account.error) notes.push("The latest usage readout failed; last values are not shown as fresh.");
    if (notes.length) root.append(element("p", "claude-reset", notes.join(" · ")));
    return root;
  }

  function render() {
    const host = byId("opencode-accounts");
    if (!host) return;
    const payload = view.payload;
    if (!payload) {
      host.replaceChildren(element("p", "claude-note", view.error || "Reading OpenCode subscriptions…"));
      return;
    }
    const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
    const summary = payload.summary || {};
    const next = when(summary.next_available_at);
    byId("opencode-freshness").textContent = payload.generated_at
      ? `${summary.subscriptions || 0} subscriptions · ${summary.ready || 0} ready · ${payload.stale ? "stale · " : ""}checked ${age(payload.generated_at)}`
      : "Status unavailable";
    const cards = accounts.map(card);
    if (!cards.length) cards.push(element("p", "claude-note", payload.error || "No OpenCode subscriptions are configured."));
    host.replaceChildren(...cards);
    byId("opencode-note").textContent = payload.error || [
      summary.ready ? null : next ? `No subscription is usable right now; the first frees up ${next}.` : null,
      "Limits come from OpenCode's plan usage readout every 5 minutes.",
      "Monthly windows renew per subscription, staggered by purchase time.",
      "OpenCode Go has no banked resets.",
    ].filter(Boolean).join(" ");
  }

  async function load() {
    try {
      const response = await fetch("/api/v1/opencode-accounts", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`opencode_http_${response.status}`);
      view.payload = await response.json();
      view.error = null;
    } catch (error) {
      view.error = "OpenCode subscription status is unavailable right now.";
    }
    render();
  }

  function initialize() {
    if (!byId("opencode-accounts")) return;
    for (const button of document.querySelectorAll(".zone-option")) {
      button.addEventListener("click", () => window.setTimeout(render, 0));
    }
    load();
    window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
