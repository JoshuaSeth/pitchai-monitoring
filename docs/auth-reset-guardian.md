# Codex reset-credit guardian

The reset-credit guardian coordinates one banked Codex usage reset when the earliest-expiring eligible account has exhausted its usable capacity. It reads broker-managed ChatGPT OAuth state, records credit-expiry warnings, and uses the same targeted backend reset-credit endpoint as the Codex app-server. It never reads or spends an OpenAI API key.

The expiry-drain policy (2026-10-01) prioritizes reviewed subscription access-end dates over fleet-wide exhaustion. It retains the durable single-redemption workflow and the older whole-fleet fallback only for accounts without a confirmed upcoming access end.

## Safety contract

One production pass obtains a single organization-wide decision as follows:

1. The guardian lists the current broker inventory. Disabled accounts are recorded but are not usable capacity and never count as evidence of exhaustion. An inventory containing no usable account is indeterminate.
2. For every enabled account, `POST /v1/admin/accounts/{account}/analytics-probe` makes the broker validate or refresh its own OAuth state and persist redacted provider analytics.
3. `GET /v1/admin/accounts/{account}/auth.json` exports the latest broker-owned auth state into process memory. Only `tokens.access_token` and `tokens.account_id` are used. `OPENAI_API_KEY`, if present in that file, is ignored.
4. Direct authenticated reads of `/wham/usage` and `/wham/rate-limit-reset-credits` obtain the authoritative usage state, every opaque credit ID, status, and expiry. The broker's redacted cached count is not trusted for redemption decisions.
5. A full measured provider window establishes exhaustion of included allowance, not of assigned credits or total effective capacity. A fresh window must have positive duration and a future reset. Effective exhaustion additionally requires coherent provider denial (`allowed=false`, `limit_reached=true`) without contradictory or unknown reported funding, or a fresh explicit provider execution-error proof from the broker matching this account and the current quota epochs. `used_percent=0` means capacity remains. Missing or stale observations, failed probes, auth errors, positive-capacity accounts, or scheduling/funding ambiguity without qualifying execution proof prevent the organization from being declared exhausted.
6. Drain enabled accounts in confirmed access-end order. Continue using the earliest account while included allowance or provider-confirmed spendable credits remain. Once that account is freshly and effectively exhausted, replenish it with one exact available, supported, unexpired banked reset before moving to later-expiring accounts. Do not wait for the whole fleet to be exhausted. If its bank is empty or deferred, continue to the next account. Unknown/stale evidence on the current target prevents redemption; unknown-date accounts retain the conservative whole-fleet fallback.
7. SQLite takes an organization decision claim inside `BEGIN IMMEDIATE` before another worker can act. The coordination fingerprint covers all usable account evidence plus the selected account, credit reference, expiry, weekly reset, and confirmed subscription end date. A partial unique index prevents concurrent runs from holding more than one active consume claim across the organization; terminal claims remain as history. A priority change never releases an unresolved mutation's claim, even after its lease expires: fresh provider reconciliation must resolve the original credit first.
8. Immediately before consuming, refresh the full inventory and reevaluate expiry order. The target must still be exhausted and the same exact account, credit, expiry, weekly reset, and subscription deadline must still be selected. New usable capacity on the target cancels the claim. Changed identity, stale evidence, or failed target refresh suppresses consume.
9. `POST /wham/rate-limit-reset-credits/consume` receives both the durable idempotency key and the exact selected credit ID. The service never issues an untargeted consume and never mass-redeems. A final exact-account refresh verifies the credit outcome, followed by a fresh full-organization refresh that must prove usable capacity has returned.

The provider can return `nothing_to_reset`. That outcome does not consume the credit. The guardian records it, emits one account + credit + expiry + outcome-scoped requester-private warning while the exact credit remains available, and may create a new logical attempt on a later pass only if fresh target-account exhaustion and eligibility are proven again. Later attempts use new logical idempotency keys; ambiguous responses and verification failures reuse the original key after reconciling provider state. Sent-key suppression prevents the waiting warning from repeating.

An unfinished credit that reaches its recorded expiry becomes `expired_unverified`, including when the provider still lists it as available. This releases the claim with an audited error, without replaying consume or claiming a successful reset.

Successful account + credit + expiry identities remain suppressed across policy changes and subscription-priority updates, including legacy attempts created before organization claims existed. A changed decision key cannot authorize replay of that completed identity.

## Subscription evidence and expiry meanings

The live source reads the existing reviewed snapshot at `/srv/codex-usage-dashboard/codex-subscriptions.json` on every account refresh, including the pre-consume recheck. It uses exact account-label matching, `access_status: active`, `renewal_enabled: false`, `access_ends_on`, a nonempty verification source, and `verified_at` no more than 30 days old and not in the future. The snapshot timezone is required for a confirmed date. Only the date, timezone, verification timestamp, and a fixed source label enter the audit; billing amounts and free-text notes are not copied.

Missing files or unconfirmed rows leave subscription ordering unknown; they never invent an end date or exclude an account from the exhaustion proof. Malformed snapshots and duplicate matching identities fail the account refresh and suppress redemption. Optional reviewed `access_ends_at` supplies the exact entitlement cutoff and must agree with `access_ends_on` in the source timezone. Cancellation timestamps do not replace entitlement expiry. Without the exact field, dates retain calendar precision: the guardian stops selecting at the beginning of the stated end day and uses the following midnight only as an upper bound when comparing the entire day with a natural reset. That bound is not stored or presented as an observed cutoff.

Quota-window reset times describe returning included capacity. Reset-credit expiry describes how long a banked reset remains redeemable. Assigned credits describe a separate usage balance and do not prove a reset is available or a subscription is ending. Subscription access-end dates come only from the reviewed billing evidence. Renewal dates are not access-end dates. Neither deadline waives fresh effective exhaustion of the selected account. Later-expiring usable accounts do not prevent replenishing that target.

When the natural weekly reset is within 48 hours and at least 96 hours remain before confirmed access ends, preserve the bank and use other eligible accounts until the natural reset. At exactly four days / two days, wait. With less than four days remaining, redeem after exhaustion even if the weekly reset is near. A banked credit that expires by the natural reset overrides waiting. Unknown end dates retain the prior two-day gate. Date-only access ends use the start of that day as a conservative lower bound for the four-day test. Each successful reset can move the weekly boundary forward seven days, so repeat decisions use fresh provider timestamps.

The service retains the broker-exported OAuth account and tenant headers for the selected account. It does not alter sessions, broker admission, disabled accounts, human-stopped workers, billing settings, or schedules. The only provider mutation is the exact banked-reset consume endpoint. Purchases, payments, top-ups, renewals, reactivation, overages, and artificial usage are outside this service.

## Execution exhaustion evidence

The existing authenticated `/wham/usage` response also supplies spending-credit, model-availability, and spend-control evidence. A source-local transport captures a typed, sanitized classification from that same response; it adds no requests and preserves the original OAuth and tenant headers. A positive decimal balance, `has_credits=true`, `unlimited=true`, model `available=true`, or `credits_would_enable=true` makes quota-only denial insufficient. Spend caps and overage flags do not prove that existing credits are unusable. Malformed or incomplete reported credit/model/control fields also require fresh matching execution proof. Explicit `has_credits=false`, `unlimited=false`, and a valid zero balance preserve ordinary coherent no-credit denial when model evidence does not contradict it.

For legacy payloads, absent optional fields remain unreported. Null model usage or spend control also means no extension was reported, and a null individual spend limit is valid. An explicitly null credit object is unknown, as are incomplete nonnull model records, nonboolean flags, and invalid balances. Only the classifications enter the audit; raw balances, model names, billing data, and usage identities are discarded. Banked reset counts never supply spending-credit evidence. Every fleet refresh replaces these classifications, including the mandatory final recheck; new funding there cancels quota-only redemption. This predicate does not authorize spending credits, overages, payments, or reloads.

The broker's read-only account detail supplies `state.execution_exhaustion`. Only version 1 with `source: provider_execution_error` and `error_code: usage_limit_reached` qualifies. It must be bound to the same broker account and retain its authenticated lease/client attribution. `occurred_at` is the actual provider-error time; `received_at` is the broker receipt time. Both must be no more than two minutes old, occurrence cannot follow receipt, and neither can follow the fresh provider observation. Recorded quota epochs must still match the currently reported windows; a reset since the failure invalidates it. Positive measured capacity cannot be overridden by the proof.

Legacy `last_reported_outcome`, `last_probe_at`, generic `rate_limited`, and timestamped outcome-only reports never qualify. Some existing clients derive those outcomes from cached numeric quota state. Read-only probes must preserve an execution proof without retimestamping it, and a legitimate success must clear it. Provider-confirmed spendable credits with permissive flags establish available capacity even beside 100% included usage. Without such confirmation or an actual execution error, contradictory funding remains indeterminate. The guardian does not generate requests to obtain proof.

Account snapshots retain only sanitized execution source, error code, occurrence/receipt times, and quota epochs; raw account IDs, lease IDs, and client names are excluded. Decision audit records label included-allowance exhaustion separately and explain whether coherent provider denial or execution failure established effective exhaustion. Assigned-credit balances and their expiration dates are never inferred from either quota percentages or banked reset inventory.

Warning deduplication, notification identity, and resumable redemption attempts are scoped by broker account reference, credit reference, and expiry. The existing version-2 audit schema remains unchanged. An additive `organization_redemption_claims` table links each organization coordination key and selected weekly reset to its ordinary `redemption_attempts` row, preserving version-1 and version-2 history without a destructive migration.

Provider behavior is why the normal weekly-distance gate exists: production history shows that verified reset consumption normally moves the weekly reset to roughly seven days after consumption, while one historical credit disappeared without a visible weekly-window move. A nearby natural reset therefore usually favors waiting. Waiting loses that benefit when confirmed subscription access ends first, or wastes a reset credit that expires first; the expiry exception addresses these cases. It never waives fresh target exhaustion or post-state verification.

Raw access/refresh tokens, broker account IDs, provider credit IDs, Authorization headers, and provider response bodies never enter logs or SQLite. Account and credit identities are stored as SHA-256 references; human-readable broker labels and expiry times remain available to operators. The runner exports only the one broker admin value needed by the guardian, removes the broker's other secret variables before `exec`, and starts the Telegram notifier with only `HOME`, `LANG`, and a fixed system `PATH`; the notifier never inherits broker or OpenAI credentials.

## Warning and redemption timing

Each available, plan-supported `codex_rate_limits` credit is warned once as it crosses each threshold:

- 48 hours
- 24 hours
- 6 hours
- 2 hours
- 1 hour

If the machine was down at a threshold, `Persistent=true` starts the missed timer and the next pass records every crossed-but-unreported threshold. Expiry thresholds are warning deadlines only; they no longer authorize or block automatic redemption. Every 15-minute pass evaluates fresh expiry-priority account exhaustion, so a qualifying event is handled without an agent process being alive. A credit may be automatically redeemed far outside the old two-hour expiry window, but only under the expiry-drain policy above. The separate manual exact-account/expiry command remains unchanged and does not widen automatic authorization.

Production warnings, non-consuming `nothing_to_reset` outcomes, account-check failures, verified redemptions, and verification failures use the canonical requester-private Telegram route `seth-ori`. There is no group route in the service configuration. Before every send, a no-send preflight proves the live route is private and the Telegram helper can query and write its durable receipt ledger. A failed preflight prevents the send, so a delivery-store outage cannot create repeated Telegram messages whose accepted receipts were never persisted. Every decision and notification result is also durable in SQLite and journald. A threshold event is recorded exactly once, while a pending or failed Telegram delivery is reconstructed from that durable threshold on later passes and retried until the private sent receipt is recorded.

## Production installation

Run from the repository root on `pitchai-dev` as root:

```bash
./ops/deploy_auth_reset_guardian.sh
```

The deployment:

- refuses deployment if any shipped file differs from `HEAD`, records the full commit SHA and a path-independent source digest, and installs an immutable release below `/opt/pitchai-auth-reset-guardian/releases/`;
- atomically points `/opt/pitchai-auth-reset-guardian/current` at that release;
- reads the broker secret only from `/etc/auth-token-server/auth-token-server.env` at run time;
- validates the canonical Telegram helper's live requester-private Seth route and required receipt-ledger table and sequence privileges without sending a message;
- runs an isolated organization-exhaustion simulation (including its negative post-capacity check) and a live no-consume dry-run;
- installs and enables `pitchai-auth-reset-guardian.timer`;
- starts one immediate live pass and verifies the persistent audit database.

The systemd timer runs on each UTC quarter-hour, survives reboots, and catches missed calendar runs. Its service is a locked one-shot, so overlapping invocations cannot make concurrent consume decisions. Both the systemd invocation and the deployment's live dry-run wait up to five minutes for the persistent audit lock. Whichever starts second is serialized whether the quarter-hour pass or deployment validation acquired the lock first, preventing a quarter-hour collision from briefly reporting the service failed. The SQLite organization claim is a second fence for concurrent processes, retries, and restarts.

## Inspecting health, logs, and audit history

```bash
systemctl status pitchai-auth-reset-guardian.timer
systemctl status pitchai-auth-reset-guardian.service
systemctl list-timers pitchai-auth-reset-guardian.timer --all
journalctl -u pitchai-auth-reset-guardian.service --since '24 hours ago' --no-pager
/usr/local/sbin/pitchai-auth-reset-guardian status
/usr/local/sbin/pitchai-auth-reset-guardian events --limit 100
```

The durable database is `/var/lib/pitchai-auth-reset-guardian/audit.sqlite3` with mode `0600` in a root-only directory. Its main records are:

- `runs`: start/completion, mode, status, and counts;
- `snapshots`: sanitized broker, usage-window, and complete credit-bank state for inventory, pre-redeem, and post-redeem phases;
- `events`: decisions, warnings, failures, notification receipts, and reconciliation evidence;
- `warning_marks`: restart-safe threshold deduplication;
- `redemption_attempts`: stable idempotency keys, provider outcomes, authoritative post-state, and verification;
- `organization_redemption_claims`: the sole active organization claim, lease, coordination key, selected weekly reset, decision fingerprint, and exact selected identity;
- `notifications`: requester-private notification attempts and their status.

Example read-only SQL:

```bash
sqlite3 -readonly /var/lib/pitchai-auth-reset-guardian/audit.sqlite3 \
  "SELECT occurred_at, account_label, event_type, severity, expires_at FROM events ORDER BY event_id DESC LIMIT 50;"
```

## Dry-run and simulation

A live dry-run performs broker refreshes and provider reads. If the initial organization decision qualifies, it also performs the complete second organization recheck, but it never claims or sends a consume request or Telegram notification:

```bash
/usr/local/sbin/pitchai-auth-reset-guardian run --dry-run --no-notify
```

The deterministic fixture exercises warnings, organization exhaustion, exact-credit targeting, fake redemption, and post-state verification without credentials or network access:

```bash
/usr/local/sbin/pitchai-auth-reset-guardian \
  --audit-db /tmp/reset-guardian-simulation.sqlite3 \
  run \
  --simulate /opt/pitchai-auth-reset-guardian/current/fixtures/auth-reset-guardian-expiring.json \
  --now 2026-08-11T19:30:00Z \
  --no-notify
```

Repository tests:

```bash
python3 -m pytest -q auth_reset_guardian/test_organization_*.py tests/test_auth_reset_guardian.py
```

## Disable, re-enable, and manual redemption

Disable future passes without deleting evidence:

```bash
systemctl disable --now pitchai-auth-reset-guardian.timer
```

If a one-shot is already running, inspect it before deciding whether to stop it. Re-enable with:

```bash
systemctl enable --now pitchai-auth-reset-guardian.timer
systemctl start pitchai-auth-reset-guardian.service
```

For a manual exact-credit operation, first copy the expiry timestamp from `status` or the provider-backed audit snapshot, then require both the exact account label and exact expiry. A dry-run is the normal first command:

```bash
/usr/local/sbin/pitchai-auth-reset-guardian manual-redeem \
  --account-label info@pitchai.net \
  --expires-at 2026-08-11T21:08:33.778745Z \
  --reason operator-verified-emergency \
  --dry-run \
  --no-notify
```

Remove `--dry-run --no-notify` only after reviewing the fresh-recheck event. The live command uses the same idempotent account + exact-ID + exact-expiry path and post-state verification as automation, but it is a distinct explicitly requested operator action and does not invoke the organization-wide automatic policy. Never use an untargeted consume call while multiple credits exist.

## Live-event interpretation

Simulation and dry-run evidence must never be described as a live redemption. A real event requires one `redemption_attempts` row, a targeted provider outcome, exact-credit post-state, full-organization post-state, and the corresponding systemd run result. If no pass meets the policy, the correct live result is “no qualifying event”: no account is preselected and no quota is manufactured for proof. The next quarter-hour evaluates all current accounts again.


Credit eligibility correction (2026-10-01): a denied included weekly window does
not block funded admission when all explicitly reported model records confirm
`available=true` and `credits_would_enable=false`, a positive/unlimited credit
balance exists, and both overage and spend-control blocks are explicitly false.
Missing or mixed model permission retains the generic quota denial. An unavailable
model with `credits_would_enable=true` describes hypothetical purchased capacity,
not existing funding; zero actual credits can therefore establish exhaustion.
