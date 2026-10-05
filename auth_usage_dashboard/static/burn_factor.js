(function () {
  "use strict";

  // Burn factor = moving capacity burn over a rolling window, times the horizon,
  // divided by the capacity the horizon makes available. Below 1: margin.
  const STORAGE_KEY = "codexusage.burnFactor.v1";
  const DEFAULT_PAIRS = [["30m", "24h"], ["24h", "6d"]];
  const PRESETS = [["30m", "6h"], ["2h", "24h"], ["6h", "3d"], ["7d", "7d"]];
  const REFRESH_MS = 30_000;
  const DURATION = /^\d{1,5}[mhd]$/;
  const STATUS = {
    good: { label: "Margin", icon: "✓" },
    tight: { label: "Tight", icon: "!" },
    short: { label: "Shortage", icon: "▲" },
    limited: { label: "At limit", icon: "◆" },
    unknown: { label: "Unknown", icon: "?" },
  };

  const view = { custom: loadCustom(), payload: null, error: null, busy: false };

  function loadCustom() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (Array.isArray(stored) && stored.length === 2 && stored.every((item) => DURATION.test(String(item)))) return stored;
    } catch (error) {
      // Storage may be unavailable; the custom card then starts empty.
    }
    return null;
  }

  function saveCustom() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(view.custom));
    } catch (error) {
      // Best effort only.
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

  function finite(value) {
    if (value === null || value === undefined || typeof value === "boolean") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function points(value) {
    const parsed = finite(value);
    if (parsed === null) return "-";
    return `${parsed.toLocaleString(undefined, { maximumFractionDigits: parsed >= 100 ? 0 : 1 })} pts`;
  }

  function durationWords(text) {
    const match = /^(\d+)([mhd])$/.exec(text || "");
    if (!match) return text || "-";
    const unit = { m: "min", h: "h", d: match[1] === "1" ? "day" : "days" }[match[2]];
    return `${match[1]} ${unit}`;
  }

  function runwayText(hours) {
    const parsed = finite(hours);
    if (parsed === null) return "Runway beyond 14 days at this burn";
    if (parsed < 1) return `Runs short in ≈ ${Math.max(1, Math.round(parsed * 60))} min at this burn`;
    if (parsed < 48) return `Runs short in ≈ ${parsed.toFixed(parsed < 10 ? 1 : 0)} h at this burn`;
    return `Runs short in ≈ ${(parsed / 24).toFixed(1)} days at this burn`;
  }

  function pairsQuery() {
    const pairs = DEFAULT_PAIRS.slice();
    if (view.custom) pairs.push(view.custom);
    return pairs.map((pair) => pair.join(":")).join(",");
  }

  function renderCard(result, index) {
    const status = STATUS[result.status] ? result.status : "unknown";
    const card = element("article", `burn-card burn-${status}`);
    const head = element("div", "burn-card-head");
    const title = element("div", "burn-card-title");
    title.append(
      element("span", "burn-card-label", index >= DEFAULT_PAIRS.length ? "Custom" : index === 0 ? "Short-term" : "Long-term"),
      element("strong", "", `${durationWords(result.rolling)} burn → next ${durationWords(result.horizon)}`)
    );
    const badge = element("span", `burn-badge burn-${status}`);
    badge.append(element("span", "burn-badge-icon", STATUS[status].icon), element("span", "", STATUS[status].label));
    head.append(title, badge);

    const factor = finite(result.factor);
    const value = element("div", "burn-factor-value");
    const prefix = result.lower_bound && factor !== null && factor < 1 ? "≥ " : "";
    value.append(element("strong", "", factor === null ? (status === "short" ? "∞" : "-") : `${prefix}${factor.toFixed(2)}`));
    value.append(element("span", "", factor === null ? "no capacity in this horizon" : "× capacity"));

    const meter = element("div", "burn-meter");
    const fill = element("span", "");
    fill.style.setProperty("--value", `${Math.min(100, Math.max(0, (factor || 0) / 2 * 100))}%`);
    meter.append(fill, element("i", "burn-meter-one"));

    const margin = finite(result.margin_points);
    const summary = element("p", "burn-summary", [
      runwayText(result.runway_hours),
      margin === null ? null : margin >= 0 ? `${points(margin)} spare over the horizon` : `${points(-margin)} short over the horizon`,
    ].filter(Boolean).join(" · "));

    const burn = result.burn || {};
    const capacity = result.capacity || {};
    const breakdown = element("dl", "burn-breakdown");
    const rows = [
      ["Burn", `${finite(burn.points_per_hour) === null ? "-" : finite(burn.points_per_hour).toFixed(1)} pts/h · ${burn.source === "native_broker_samples" ? `${burn.coverage_percent}% sampled · ${burn.confidence}` : "current-window estimate"}`],
      ["Needed", points(result.demand_points)],
      ["Available", `${points(capacity.effective_points)} = ${points(capacity.left_now_points)} left + ${capacity.reset_count || 0} reset${capacity.reset_count === 1 ? "" : "s"} (${points(capacity.reset_points)}) − ${points(capacity.expiring_points)} expiring at resets − ${points(capacity.subscription_expiring_points)} lost to ${capacity.subscription_end_count || 0} subscription end${capacity.subscription_end_count === 1 ? "" : "s"}`],
    ];
    for (const [label, text] of rows) breakdown.append(element("dt", "", label), element("dd", "", text));

    const notes = [];
    if (result.reason) notes.push(result.reason);
    if (result.lower_bound) notes.push(`${capacity.saturated_accounts} of ${capacity.eligible_accounts} accounts are at their limit; their work is not visible as quota burn, so the real factor is at least this.`);
    if (capacity.credit_accounts) notes.push(`${capacity.credit_accounts} account${capacity.credit_accounts === 1 ? "" : "s"} can run on spendable credits beyond quota (not counted).`);
    if (capacity.ended_subscription_accounts) notes.push(`${capacity.ended_subscription_accounts} account${capacity.ended_subscription_accounts === 1 ? "" : "s"} excluded: subscription already ended.`);
    card.append(head, value, meter, summary, breakdown);
    if (notes.length) card.append(element("p", "burn-note", notes.join(" ")));
    return card;
  }

  function render() {
    const grid = byId("burn-factor-grid");
    if (!grid) return;
    grid.classList.toggle("is-refreshing", view.busy);
    const results = view.payload && Array.isArray(view.payload.results) ? view.payload.results : [];
    if (!results.length) {
      grid.replaceChildren(element("p", "burn-empty", view.error || "Reading burn and capacity…"));
      return;
    }
    grid.replaceChildren(...results.map(renderCard));
    const basis = (view.payload.basis || {}).label;
    byId("burn-factor-basis").textContent = basis ? `${basis} capacity points · 100 = one full account window` : "Capacity basis not reported";
  }

  async function load() {
    if (view.busy) return;
    view.busy = true;
    render();
    try {
      const response = await fetch(`/api/v1/burn-factor?pairs=${encodeURIComponent(pairsQuery())}`, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`burn_factor_http_${response.status}`);
      view.payload = await response.json();
      view.error = null;
    } catch (error) {
      view.error = "Burn factor is unavailable right now.";
    } finally {
      view.busy = false;
    }
    render();
  }

  function applyCustom(rolling, horizon) {
    const cleanRolling = String(rolling || "").trim().toLowerCase();
    const cleanHorizon = String(horizon || "").trim().toLowerCase();
    const message = byId("burn-custom-message");
    if (!DURATION.test(cleanRolling) || !DURATION.test(cleanHorizon)) {
      message.textContent = "Use values like 45m, 3h or 2d.";
      return;
    }
    message.textContent = "";
    view.custom = [cleanRolling, cleanHorizon];
    saveCustom();
    load();
  }

  function initialize() {
    const form = byId("burn-custom-form");
    if (!form) return;
    const rollingInput = byId("burn-custom-rolling");
    const horizonInput = byId("burn-custom-horizon");
    if (view.custom) {
      rollingInput.value = view.custom[0];
      horizonInput.value = view.custom[1];
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      applyCustom(rollingInput.value, horizonInput.value);
    });
    const presets = byId("burn-presets");
    for (const [rolling, horizon] of PRESETS) {
      const chip = element("button", "burn-preset", `${rolling} → ${horizon}`);
      chip.type = "button";
      chip.addEventListener("click", () => {
        rollingInput.value = rolling;
        horizonInput.value = horizon;
        applyCustom(rolling, horizon);
      });
      presets.appendChild(chip);
    }
    load();
    window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, REFRESH_MS);
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
