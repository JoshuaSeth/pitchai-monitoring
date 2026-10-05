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

  const POOLS = [
    ["openai", "OpenAI", "Codex account broker"],
    ["anthropic", "Anthropic", "Claude Code accounts"],
    ["opencode", "OpenCode Go", "MiMo / GLM subscription pool"],
  ];
  const view = { custom: loadCustom(), payloads: {}, errors: {}, busy: false };

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
    const limited = status === "limited";
    // While most accounts sit at their limit their burn is invisible, so neither runway nor spare is knowable.
    const capacityNow = result.capacity || {};
    const noCapacity = finite(capacityNow.effective_points) === 0;
    const summary = element("p", "burn-summary", noCapacity ? "No usable capacity inside this window" : [
      limited ? "Runway not measurable while accounts sit at their limit" : runwayText(result.runway_hours),
      limited ? `${points((result.capacity || {}).effective_points)} available over the horizon`
        : margin === null ? null : margin >= 0 ? `${points(margin)} spare over the horizon` : `${points(-margin)} short over the horizon`,
    ].filter(Boolean).join(" · "));

    const burn = result.burn || {};
    const capacity = result.capacity || {};
    const breakdown = element("dl", "burn-breakdown");
    const rows = [
      ["Burn", `${finite(burn.points_per_hour) === null ? "-" : finite(burn.points_per_hour).toFixed(1)} pts/h · ${burn.source === "native_broker_samples" ? `${burn.coverage_percent}% sampled · ${burn.confidence}` : "current-window estimate"}`],
      ["Needed", points(result.demand_points)],
      ["Available", `${points(capacity.effective_points)} = ${points(capacity.left_now_points)} left + ${capacity.reset_count || 0} reset${capacity.reset_count === 1 ? "" : "s"} (${points(capacity.reset_points)}) − ${points(capacity.expiring_points)} expiring at resets − ${points(capacity.subscription_expiring_points)} lost to ${capacity.subscription_end_count || 0} subscription end${capacity.subscription_end_count === 1 ? "" : "s"}${finite(capacity.blocked_points) ? ` − ${points(capacity.blocked_points)} blocked` : ""}`],
    ];
    for (const [label, text] of rows) breakdown.append(element("dt", "", label), element("dd", "", text));

    const notes = [];
    if (result.reason) notes.push(result.reason);
    if (result.lower_bound && capacity.saturated_accounts) notes.push(`${capacity.saturated_accounts} of ${capacity.eligible_accounts} accounts are at their limit; their work is not visible as quota burn, so the real factor is at least this.`);
    if (capacity.credit_accounts) notes.push(`${capacity.credit_accounts} account${capacity.credit_accounts === 1 ? "" : "s"} can run on spendable credits beyond quota (not counted).`);
    if (capacity.blocked_accounts) notes.push(`${capacity.blocked_accounts} account${capacity.blocked_accounts === 1 ? " is" : "s are"} blocked by another exhausted window (5-hour or monthly) until ${capacity.blocked_until ? new Date(capacity.blocked_until).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "its reset"}; ${points(capacity.blocked_points)} stay unusable inside this window.`);
    if (capacity.ended_subscription_accounts) notes.push(`${capacity.ended_subscription_accounts} account${capacity.ended_subscription_accounts === 1 ? "" : "s"} excluded: subscription already ended.`);
    if (status === "unknown") {
      card.append(head, value, element("p", "burn-summary", result.reason || "Not enough data yet for this pool."));
      return card;
    }
    card.append(head, value, meter, summary, breakdown);
    if (notes.length) card.append(element("p", "burn-note", notes.join(" ")));
    return card;
  }

  function renderPool(pool) {
    const [key, name, detail] = pool;
    const block = element("section", "burn-pool");
    block.dataset.pool = key;
    const payload = view.payloads[key];
    const head = element("div", "burn-pool-head");
    const title = element("div", "burn-pool-title");
    title.append(element("h3", "", name), element("span", "", detail));
    const basis = payload && payload.basis && payload.basis.label ? `${payload.basis.label} points · 100 = one full account window` : "Capacity basis not reported";
    head.append(title, element("span", "burn-pool-basis", basis));
    const grid = element("div", "burn-grid");
    grid.classList.toggle("is-refreshing", view.busy);
    const results = payload && Array.isArray(payload.results) ? payload.results : [];
    if (!results.length) grid.append(element("p", "burn-empty", view.errors[key] || "Reading burn and capacity…"));
    else grid.append(...results.map(renderCard));
    block.append(head, grid);
    return block;
  }

  function render() {
    const host = byId("burn-factor-pools");
    if (!host) return;
    host.replaceChildren(...POOLS.map(renderPool));
  }

  async function loadPool(key) {
    try {
      const query = `pool=${encodeURIComponent(key)}&pairs=${encodeURIComponent(pairsQuery())}`;
      const response = await fetch(`/api/v1/burn-factor?${query}`, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`burn_factor_http_${response.status}`);
      view.payloads[key] = await response.json();
      view.errors[key] = null;
    } catch (error) {
      view.errors[key] = "Burn factor is unavailable right now.";
    }
  }

  async function load() {
    if (view.busy) return;
    view.busy = true;
    render();
    try {
      await Promise.all(POOLS.map(([key]) => loadPool(key)));
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
