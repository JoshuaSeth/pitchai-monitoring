# Spec: Burn factor (moving burn rate vs. horizon capacity) on codexusage.pitchai.net

Status: approved for build 2026-10-05 · branch `feat/usage-layers-claude-limits-20261005` · scope: monitoring repo only

## Request (verbatim)

"""perfect now lets also make this visible in the dashboard page. and also that i can request this with any rolling
average/future windows. the defaults we can show is 30m rolling / 24h future window and 24h rolling with 6d future
window, understand? : 30 minute moving burn rate / capacity for 6h 24h, etc. anything above 1.0 is problem, more burn
then capacity, anything below is "good" less burn. for example 0.5 on 24h block means that with current moving burn
rate we can get 48h ahead. capacity is existing capacity + weekly resets. so weekly reset in coming 3 hours means 3
hours * current usage left + 21 hours * full usage left. so then I can always ask for the burn factor over 24h and know
how much margin or shortage we have. so get this researched, get spec made and get spec impleneted built, commited pred
merged to origin main and staging and dpelyoed in the main dahsboard so it can't get lost."""

## Definition

For a rolling window **W** (how far back the burn rate is measured) and a future horizon **H**:

```
burn rate      B = capacity points burned in the last W  /  W (hours)     [points per hour]
demand         D = B × H                                                  [points]
capacity       C = Σ eligible accounts ( points left now  +  100 × resets inside H )
                   − points that expire unused at a reset at this burn rate
burn factor    F = D / C
```

- **One capacity point** is 1% of one account's provider window on the dashboard's declared capacity basis. Today that
  basis is weekly, because the provider no longer exposes a 5-hour window. A full account window is 100 points.
- **Eligible accounts** are the same broker-burnable set the scheduling capacity endpoint uses: enabled, auth-valid and
  fresh (`eligible_account`). Disabled, auth-invalid and stale accounts contribute nothing.
- **Points left now** is each account's measured `remaining_percent` on the basis window. Unknown windows contribute 0
  and are counted as unknown accounts; they are never treated as 0% used or as a full window.
- **Resets inside H**: each account's reported `reset_at`, then every `window_seconds` after it, up to now + H. Each
  reset restores the account to a full window (100 points).
- **Use it or lose it**: whatever an account still has left at its reset is replaced by a fresh window, not added to
  it. Your example of a weekly reset in 3 hours with H = 24h works out as follows:
  - The account offers its current leftover for 3 hours.
  - It then offers a full window for the remaining 21 hours.
  - The leftover only counts as far as the burn can actually consume it before the reset.

  The calculation simulates the pool at constant burn B. It works in 1-minute steps across H and serves demand from
  the account whose reset comes first (expiring points first). Leftover still unconsumed at a reset is reported as
  `expiring_points` and is not counted as capacity.
- **Reading F**: `F < 1` means margin and `F ≥ 1` means shortage. The status label is `good` below 0.85, `tight` from
  0.85 up to 1.0, and `short` from 1.0 up.
  - Example: F = 0.5 over 24h means the current burn uses half of what the next 24h make available.
- **Runway**: the time until the simulated pool can no longer serve B, simulated up to 14 days. This is where "0.5 on
  24h ≈ 48h ahead" comes from; the simulation also accounts for resets falling after H. It is reported as
  `runway_hours`, or as `beyond_hours: 336` when the pool lasts the whole simulation.
- **Margin / shortage**: `C − D` points. A positive value is spare capacity over H; a negative value is the shortfall.

### Burn measurement

- B comes from the dashboard's own 5-minute broker samples, which hold 8 days of history. It uses the existing
  reset-aware delta measurement (`measure_burn_samples`):
  - It counts only increases in used percentage between consecutive samples of the same eligible account.
  - It skips intervals that cross a provider reset or a counter regression, or that have a gap longer than 20 minutes.
  - It clips intervals at the window boundary.
- The rate is the measured points divided by the covered hours, not by W. A gap therefore does not dilute the rate,
  and the response reports `coverage_percent` and `confidence`.
- With no covered interval, the existing current-window average estimate is used and labelled `estimate`.
- W can be anything from 5 minutes to 7 days (sample retention is 8 days). H can be anything from 1 hour to 14 days.

## API

`GET /api/v1/burn-factor?pairs=30m:24h,24h:6d` is SSO-protected like every account route.

- `pairs` takes 1–6 comma-separated `rolling:horizon` pairs. Durations are written as `<n>m`, `<n>h` or `<n>d`; an
  out-of-range or unparsable value gives HTTP 400.
- The default is `30m:24h,24h:6d`.
- Each result carries `rolling`, `horizon`, `rolling_seconds`, `horizon_seconds`, `factor`, `status`, `runway_hours`,
  `margin_points`, plus:

```
burn:     {points_per_hour, measured_points, coverage_percent, confidence, source}
capacity: {left_now_points, reset_points, reset_count, expiring_points, effective_points, eligible_accounts, unknown_accounts}
demand_points
basis:    {key, label}
```

- Results come from the cached capacity snapshot and the sample store. Responses are cached for 30 s per pairs value
  and computed in a worker thread.
- If the basis is unknown or no account is eligible, `factor` is null and the result says why.

## UI

- A **Burn factor** section sits directly below the "Capacity now" decision band. It shows two default cards (30-min
  burn → next 24 h, 24-h burn → next 6 days).
- Each card has:
  - the factor in large type with a status badge (icon + label; never colour alone);
  - "≈ N h runway" and the margin or shortage in points;
  - a breakdown: burn pts/h (coverage), demand, and capacity = left now + resets − expiring.
- A **Custom** row has two inputs (rolling, horizon) that accept values like `45m`, `3h`, `2d`, with preset chips.
  It adds a third card and remembers the last custom pair in the browser.
- The section refreshes with the capacity snapshot, which polls every 30 s. The server cache keeps the cost flat.

## DeepSeek API pool (prepaid money, added 2026-10-05)

Request (verbatim): "finally ideally also integrate in the dashboard the api burn rate we have for deepseek (api based
not account) and the amount left on the deepseek dashboard."

DeepSeek is not an account pool. One prepaid API account is billed per token, and every DeepSeek owner on master,
jeff-dev and fsn1 uses the same key. So:

- **Capacity** is the remaining balance: `total_balance` from `GET https://api.deepseek.com/user/balance`, USD row.
  `deepseek-balance-export.timer` reads the owners' `0600` `api-key` files in-process every 5 minutes and writes
  numbers only to `deepseek-balance.json`.
- **Burn** is dollars per hour, estimated from the fleet token ledger. It covers every `provider = deepseek` hour
  (`deepseek-*` models), whichever owner route ran it. The engine's price snapshot `deepseek-flash-2026-09-16`
  (`pitchai_cli_new.deepseek_usage`) sets the rates: $0.003/M cached input, $0.15/M uncached input and $0.60/M
  output, x2 on weekdays 01-04 and 06-10 UTC. Ledger buckets are hourly. Buckets that straddle the rolling window are
  prorated by overlap. The current hour counts only up to the ledger's last delivery (`MAX(received_at)`).
- **Factor** = burn per hour x horizon hours / balance. Runway is balance / burn. An empty balance is a shortage,
  even at zero current burn, because DeepSeek refuses requests (402).
- Each result also reports the **7-day pace** (average dollars per hour over the last week) and what the horizon
  costs at that pace, so a top-up can be sized while the account is empty.
- API: `pool=deepseek` returns `unit: "usd"`, `balance {total_usd, granted_usd, topped_up_usd, is_available,
  observed_at, stale}`, `price {snapshot, source, peak}` and results with `burn.usd_per_hour`, `demand_usd`,
  `available_usd`, `margin_usd`, `runway_hours` and `typical`.

## Non-goals

- Claude accounts are left out: there is no Claude history store yet, and these are Codex broker capacity points.
- Credits (spendable balances) are left out. Points are quota percentages, as in the existing runout forecast.
- Banked resets are left out. Redemption is manual and forbidden here.

## Rollout

The burn factor ships with the same branch as the token ledger and Claude meters. It merges to `staging` via PR #216
and to `main` via a main-parity PR, after the strict quality ratchet passes. The dashboard is then deployed with
`ops/deploy_codex_usage_dashboard.sh` from the merged `main` and verified on the live API.
