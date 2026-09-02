# Codex authentication-broker capacity dashboard

`https://codexusage.pitchai.net` is the protected operator view for the authoritative Codex authentication broker on `pitchai-dev`.

## Architecture

- Nginx terminates TLS and delegates browser authentication to the shared PitchAI Entra broker.
- Nginx injects a normalized `X-PitchAI-Email` only after successful Microsoft 365 authentication.
- The dashboard listens only on `127.0.0.1:8124` and rejects UI/API requests without that trusted header.
- The container mounts `/srv/auth-token-server/data/accounts` read-only and reads only `metadata.json` and `state.json`. It never opens `auth.json`.
- The inventory is directory-driven: every broker account with `metadata.json` is sampled, including disabled, auth-invalid, and temporarily state-missing accounts. No separate dashboard allowlist can silently omit an account.
- The broker admin token is passed only to the container process so it can trigger the broker's account usage probe endpoint. It is never returned, logged, or embedded in the page.
- `/healthz` is intentionally unauthenticated and exposes only service health, generation time, and a stale boolean. All account-bearing routes require authentication.

The personal Codex Status iPhone app uses a separate, narrow mobile API under
`/api/v1/mobile/`. That location bypasses browser SSO because native background
refresh cannot complete an interactive Entra flow, but it does not use a bearer
token, cookie, password, or embedded broker credential. Every account-bearing
request instead requires a one-time challenge and a monotonic assertion from an
Apple App Attest key registered for `ZM6568G5FX.com.pitchai.codexstatus`.
Nginx clears browser identity, authorization, and cookie headers before proxying
the location, limits request bodies, and rate-limits challenge traffic. The API
returns a deliberate subset of the dashboard snapshot: labels, current states,
remaining percentages, reset times, warnings, and freshness only. Emails,
broker IDs, token analytics, reset inventory, and credentials are excluded.

The Watch app never calls the service. The signed iPhone app sends the redacted
native snapshot through WatchConnectivity, and both WidgetKit extensions read
the same App Group cache. The opaque App Attest key identifier is the only
authentication-related value stored by the app; the private key remains in
Apple's App Attest service and cannot be exported.

The broker state files are root-only (`0600`). The production container therefore runs as container root with all Linux capabilities dropped, `no-new-privileges`, a read-only root filesystem, a small temporary filesystem, and only the broker accounts directory mounted read-only. The app has no endpoint that reads arbitrary files.

## Freshness and probe cost

The service rereads broker state every 15 seconds, runs a no-generation quota probe at most once every 5 minutes, and refreshes token history plus the reset bank at most once every 15 minutes. A manual refresh is throttled to one probe per minute.

The probe calls the broker's existing `POST /v1/admin/accounts/{id}/probe` endpoint. That endpoint refreshes auth if needed and calls the Codex usage endpoint; it does not submit a prompt or run a model generation. The dashboard deliberately discards the secret-bearing admin response body and rereads only redacted state files.

The analytics refresh calls the broker's `POST /v1/admin/accounts/{id}/analytics-probe` endpoint. The broker then uses the same refreshed account auth to issue provider `GET` requests to `/wham/profiles/me` and `/wham/rate-limit-reset-credits`. Only daily token buckets, aggregate token statistics, reset counts, display titles, statuses, and grant/expiry dates enter `state.json`. Provider profile fields, reset-credit IDs, and every credential field are dropped before persistence. The provider exposes daily history; the chart reconstructs a clearly labeled hourly series that preserves those daily totals and marks the current hour partial.

This keeps quota metadata current without creating synthetic model work. Reducing the probe interval below five minutes is discouraged because it increases provider and auth traffic without improving operator decisions.

## Capacity model

One normalized capacity point equals one percentage point of the provider-window basis declared in the snapshot. One full account window is therefore 100 points. The dashboard prefers a five-hour basis when that window is authoritatively reported for at least half of fresh auth-valid accounts; otherwise it uses the reported weekly window. It never relabels weekly data as five-hour data.

- Current headroom contributes the selected window's measured remaining percentage for fresh, selectable accounts.
- An automatic reset inside the selected horizon contributes 100 scheduled points when auth and quota state permit it.
- Weekly exhaustion remains a hard block until the weekly reset. When weekly is the selected basis, weekly percentage points and reset times are modeled directly and labeled as weekly.
- The 1-hour, 6-hour, and 24-hour percentages compare usable points with the configured pool's theoretical points over that horizon. They are an operational ceiling, not a token forecast or guaranteed throughput.
- Stale, auth-invalid, disabled, and unknown accounts do not contribute usable points.
- The broker safety floor is honored. An account at or below `AUTH_TOKEN_SERVER_MIN_FIVE_HOUR_REMAINING_PERCENT` is shown as five-hour limited even if the provider still reports a small remainder.

### Luna reserve capacity

The prominent Luna panel is a separate meter; it is not another rendering of
the main five-hour or weekly capacity pool. It counts only a provider additional
limit whose outer record has `limit_name=gpt-reserve` and
`metered_feature=base_model_inference`, with availability and windows read from
that record's nested `rate_limit` object. Public `gpt-5.6-luna`, Spark, generic
quota windows, and unrecognized additional limits are excluded.

The provider model catalog currently exposes public `gpt-5.6-luna` and hides
`gpt-reserve`, while reporting matching context, input, tool, output, and
reasoning-level capabilities for both. The dashboard therefore labels the
separate meter **Luna-equivalent reserve**. The catalog calls Luna fast and
affordable, but exposes no auditable currency price; the UI does not invent a
dollar saving. Reliability remains `awaiting_first_canary` until a controlled
production route has completed successfully.

For each entitled account the dashboard shows the measured remainder, provider
reset, health, routing tier, and policy-safe drain percentage after preserving
`AUTH_TOKEN_SERVER_MIN_LUNA_RESERVE_REMAINING_PERCENT` (default 20%). The top
panel separates:

- total and remaining measured reserve points;
- all policy-safe points after the per-account floor;
- policy-safe points on the active standard app-server lease, which are the
  only points the current shared scheduler can drain without changing accounts;
- safe points stranded on a main-exhausted or otherwise unusable shared account;
- safe points held on the protected last-resort account, which low-priority
  reserve routing must never use.

An active session alone does not make reserve routable. The same account must
remain enabled, auth-valid, fresh, explicitly reserve-allowed, below neither
provider nor broker floors, generic-main eligible, and standard tier. This
protects Sol/Terra continuity: the shared app server is never moved onto a
main-exhausted account merely to harvest its reserve meter. The panel is
read-only and does not submit a model request, acquire a lease, switch an
account, or enable scheduler routing.

Provider window names are not stable identifiers. The dashboard classifies reported windows by duration: four to six hours is the five-hour window, and six days or longer is the weekly window. A missing five-hour window remains `null` in the API and is labeled **Provider does not expose 5h** in that specific table cell; it is never interpreted as 0% remaining or as a full five-hour window. Weekly columns, aggregate forecasts, runout estimates, and reset arrivals continue to use authoritative weekly data when available. Aggregate percentages include explicit reporting and unknown-account counts.

OpenAI currently appears to have temporarily removed or disabled the five-hour
window for some or all accounts. Treat that as a reversible provider capability
change, not an account failure or dashboard outage. A window without an
authoritative duration is also unclassified: field position, reset proximity,
and historical shape must not be used to manufacture a five-hour measurement.
The parser reevaluates every fresh response, so a restored four-to-six-hour
window will automatically reappear without a configuration change. Until then,
only the five-hour cells and five-hour-specific aggregate are unavailable;
account validity, selectability, weekly headroom/resets, reset-bank inventory,
usage history, capacity arrivals, and weekly-based forecasts remain
operational.

Capacity arrivals list automatic provider-window resets across the next eight days. Banked reset expiry dates are shown only in the separate read-only reset bank; expiry is a deadline, not an automatic capacity arrival.

Banked resets use the provider's read-only reset inventory. The UI shows every grant and expiry date returned by the provider, ordered by expiry. When only a count is available, the dashboard says dated detail is unavailable rather than inventing it. Neither the broker analytics endpoint nor the dashboard implements the provider's reset-consumption action; redeeming a reset is outside this service's capability.

## Durable usage-limit history, hourly history, and runout forecast

The provider profile route reports historical token totals by UTC day, not hour. The dashboard reconstructs 168 hourly points with an even, daily-total-constrained allocation and applies a three-hour smoothing window for the line plot. Every complete raw reconstructed day still sums exactly to the provider total. The API marks each hour as `reconstructed`, `blended`, or `observed`; it does not present reconstructed hours as provider-observed facts.

The production container appends one complete inventory batch every five minutes to `/srv/codex-usage-dashboard/usage-history.sqlite3`. This matches the broker's existing no-generation quota-probe cadence, so collecting history does not add prompts, model turns, token use, or provider calls. The collector rereads redacted broker state and never opens `auth.json`. Five minutes is the minimum supported cadence; sampling faster would duplicate unchanged provider snapshots and grow the store without adding operational information.

The SQLite database uses WAL mode, full synchronization, foreign keys, a 30-second busy timeout, schema-version validation, and append-only batch/account tables. Each account row stores the UTC sample time, label, SHA-256 broker-account fingerprint, enabled/auth/availability state, five-hour and weekly used/remaining percentages, reset times and window durations, redeemable count, provider and analytics observation times/staleness, sanitized error codes, data provenance, source, and full collector Git SHA. Auth-invalid accounts still receive a row. Missing measurements are copied from that account's most recent row only when available and are explicitly marked `values_source=last_known`, never current.

The root-owned database directory is mode `700`; the database, WAL, shared-memory files, and deployment backups are mode `600`. The SQLite series is not automatically pruned. At the current small account inventory, this preserves long-running structural history while reporting queries remain time- and row-bounded. Before each production replacement, the deployment script uses SQLite's online backup API and `quick_check` to create a timestamped copy under `/srv/codex-usage-dashboard/backups`. The former `/srv/codex-usage-dashboard/usage-samples.json` is transactionally imported once on first collection and then retained as migration evidence.

The JSON ledger continues as an eight-day compatibility input for the dashboard's token reconstruction and burn-rate calculations. Native usage deltas progressively replace reconstructed hourly allocations, and native percentage deltas for the declared provider-window basis provide the preferred trailing two-hour burn estimate. Historical samples written before schema v4 are recovered as weekly only when their reset was more than six hours away at observation time, which makes a five-hour interpretation impossible. It is no longer the authoritative durable history.

Runout probability uses deterministic burn-rate scenarios around the trailing two-hour sample rate. Until enough native samples exist, the UI labels a current-window average estimate and lowers confidence. Capacity is consumed earliest-reset-first and automatic resets for the declared basis are modeled. If no five-hour window is reported but weekly data is authoritative, the forecast explicitly uses weekly percentage points; if neither window is available, the forecast is unavailable rather than inferred as 0% or 100%. Banked resets never enter forecast capacity because they require a forbidden manual redemption action.

## Operations

Build and deploy the container from the repository root:

```bash
sudo ops/deploy_codex_usage_dashboard.sh
```

New mobile keys are closed by default. For a deliberate first-device enrollment,
deploy once with the enrollment gate open, launch the signed app on that device,
verify the registry contains the new key, and immediately redeploy the same image
with the gate closed:

```bash
AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED=1 \
  sudo ops/deploy_codex_usage_dashboard.sh
AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED=0 \
  sudo ops/deploy_codex_usage_dashboard.sh codex-usage-dashboard:<git-sha>
```

The registry lives at
`/srv/codex-usage-dashboard/mobile-app-attest.json` as `0600 root:root` and
contains public keys, Apple receipts, assertion counters, and timestamps only.
Do not print or copy it into task logs. Reinstallation or device replacement
requires an operator to reopen this enrollment gate intentionally.

The script is intentionally host-locked to `pitchai-dev`. It validates the broker service and root-only credential source, builds an immutable Git-SHA image, starts a read-only canary on loopback without probing, checks the redacted API, and then replaces the production container with automatic rollback to the previous image if the post-check fails.

Post-deploy checks:

```bash
curl --fail --silent http://127.0.0.1:8124/healthz
curl --fail --silent -H 'X-PitchAI-Email: deployment-check@pitchai.net' \
  http://127.0.0.1:8124/api/v1/capacity | jq '.summary'
docker inspect codex-usage-dashboard --format '{{.State.Status}} {{.State.Health.Status}}'
docker exec codex-usage-dashboard python -m auth_usage_dashboard.history_cli \
  --database /dashboard-data/usage-history.sqlite3 status
docker exec codex-usage-dashboard python -m auth_usage_dashboard.history_cli \
  --database /dashboard-data/usage-history.sqlite3 summary --hours 24
```

Do not print the full API response in shared logs. It contains account labels and usage state, though it contains no credentials.

Read recent history for one exact broker label, or bounded rows from the last 24 hours:

```bash
docker exec codex-usage-dashboard python -m auth_usage_dashboard.history_cli \
  recent --account 'seth.vanderbijl@pitchai.net' --limit 20
docker exec codex-usage-dashboard python -m auth_usage_dashboard.history_cli \
  history --hours 24 --limit 10000
```

All reports are read-only JSON. `summary --hours 24` is the preferred monitoring proof because it returns per-account sample counts, first/last timestamps, maximum gap, auth-invalid count, provider-stale count, and last-known count without exposing credentials or broker account IDs.

## Nginx, DNS, and access

- DNS: `codexusage.pitchai.net` A record to the public IPv4 address of `pitchai-dev`.
- HTTP bootstrap source: `ops/codexusage.pitchai.net.bootstrap.nginx.conf`.
- Nginx source: `ops/codexusage.pitchai.net.nginx.conf`.
- Browser authentication: shared broker at `https://auth.pitchai.net` using the domain-wide secure SSO cookie.
- TLS: Certbot-managed certificate for `codexusage.pitchai.net`.
- Certificate renewal: `ops/renew_codexusage_certificate.sh` through the committed systemd service and timer.
- External canary: the monitoring service checks the redacted `/healthz` response, DNS, TLS, and browser reachability. Docker performs the local container health check on `pitchai-dev`.

Only a broker-verified `@pitchai.net` Microsoft identity can reach the browser UI. The legacy Basic Auth file is not referenced by this vhost and is retained only for rollback diagnosis.

For a first deployment, install and enable the HTTP bootstrap vhost, run `nginx -t`, and reload Nginx before requesting the certificate. Once the certificate exists, replace the bootstrap file with the final Nginx source, validate again, and reload. This keeps the ACME challenge reachable without making Nginx depend on a certificate that has not been issued yet.

The host's legacy Certbot Python environment is not used for this certificate. Install `ops/renew_codexusage_certificate.sh` as `/usr/local/sbin/renew-codexusage-certificate`, install the two committed unit files in `/etc/systemd/system`, then enable `codexusage-cert-renew.timer`. The script pins the working official Certbot container image and renews only this certificate; it reloads Nginx only when the certificate fingerprint changes.

## Rollback

To redeploy a known image:

```bash
sudo ops/deploy_codex_usage_dashboard.sh codex-usage-dashboard:<git-sha>
```

Application rollback does not roll back or replace the append-only history database. If a database migration must be reversed, stop the dashboard container, preserve the current database, validate the selected file from `/srv/codex-usage-dashboard/backups` with `PRAGMA quick_check`, and only then restore it. The legacy JSON ledger remains available for migration recovery.

For an Nginx rollback, restore the timestamped backup beside `/etc/nginx/sites-available/codexusage.pitchai.net`, run `nginx -t`, and reload Nginx. DNS removal is not needed for a short application rollback; the protected proxy can return a controlled maintenance response while the prior container is restored.

## Data safety invariants

- No `auth.json`, access token, refresh token, broker token, password, device code, callback code, or mailbox code may enter the API, DOM, logs, screenshots, tests, or repository.
- Mobile account data requires a verified App Attest assertion; the public mobile location accepts no browser SSO identity or reusable application credential.
- Token history and reset-bank collection is GET-only at the provider boundary. Reset redemption is forbidden and has no dashboard route or control.
- The dashboard-owned history mount is the only writable persistent path in the read-only container.
- Active requester/session counts are informational telemetry only. They never reduce account availability.
- Only actual auth validity, provider rate/quota state, disabled state, freshness, and the broker safety floor affect displayed selectability.
