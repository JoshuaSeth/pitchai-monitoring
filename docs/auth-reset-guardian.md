# Codex reset-credit guardian

The reset-credit guardian coordinates one banked Codex usage reset when the authentication broker proves that the whole usable organization is out of capacity. It reads broker-managed ChatGPT OAuth state, records credit-expiry warnings, and uses the same targeted backend reset-credit endpoint as the Codex app-server. It never reads or spends an OpenAI API key.

Current policy task: `AUTH-BROKER-ORG-EXHAUSTION-REDEMPTION-20260907`. The earlier expiry-protection implementation is tracked by `AUTH-BROKER-RESET-AUTOMATION-20260810`.

## Safety contract

One production pass obtains a single organization-wide decision as follows:

1. The guardian lists the current broker inventory. Disabled accounts are recorded but are not usable capacity and never count as evidence of exhaustion. An inventory containing no usable account is indeterminate.
2. For every enabled account, `POST /v1/admin/accounts/{account}/analytics-probe` makes the broker validate or refresh its own OAuth state and persist redacted provider analytics.
3. `GET /v1/admin/accounts/{account}/auth.json` exports the latest broker-owned auth state into process memory. Only `tokens.access_token` and `tokens.account_id` are used. `OPENAI_API_KEY`, if present in that file, is ignored.
4. Direct authenticated reads of `/wham/usage` and `/wham/rate-limit-reset-credits` obtain the authoritative usage state, every opaque credit ID, status, and expiry. The broker's redacted cached count is not trusted for redemption decisions.
5. An account is exhausted only when a fresh measured provider window has `used_percent=100` (zero remaining capacity) and the provider coherently reports `allowed=false` and `limit_reached=true`. `used_percent=0` means full capacity remains; it is never exhaustion. Missing or stale observations, failed probes, auth errors, positive-capacity accounts, or contradictory scheduling flags prevent the organization from being declared exhausted.
6. Redemption is considered only when every enabled account is freshly and coherently exhausted. Among exhausted accounts with an exact available, plan-supported, unexpired credit and an identifiable weekly window, only accounts whose natural weekly reset is strictly more than 48 hours away are eligible. Exactly 48 hours is ineligible. The account whose weekly reset is furthest away wins; its earliest-expiring eligible credit is selected deterministically.
7. SQLite takes an organization decision claim inside `BEGIN IMMEDIATE` before another worker can act. The coordination fingerprint covers all usable account evidence plus the selected account, credit reference, expiry, and weekly reset. A partial unique index prevents concurrent runs from holding more than one active consume claim across the organization; terminal claims remain as history.
8. Immediately before consuming, the guardian lists the broker accounts again and repeats the full broker/OAuth/provider refresh for every enabled account. The whole organization must still be exhausted and the same account, exact credit reference, exact expiry, and weekly reset must still be selected. A changed expiry or weekly reset is a loud audited error. Any other changed, stale, missing, or failed evidence cancels a new claim and suppresses the consume.
9. `POST /wham/rate-limit-reset-credits/consume` receives both the durable idempotency key and the exact selected credit ID. The service never issues an untargeted consume and never mass-redeems. A final exact-account refresh verifies the credit outcome, followed by a fresh full-organization refresh that must prove usable capacity has returned.

The provider can return `nothing_to_reset`. That outcome does not consume the credit. The guardian records it, emits one account + credit + expiry + outcome-scoped requester-private warning while the exact credit remains available, and may create a new logical attempt on a later pass only if fresh organization-wide exhaustion and eligibility are proven again. Later attempts use new logical idempotency keys; ambiguous responses and verification failures reuse the original key after reconciling provider state. Sent-key suppression prevents the waiting warning from repeating.

Warning deduplication, notification identity, and resumable redemption attempts are scoped by broker account reference, credit reference, and expiry. The existing version-2 audit schema remains unchanged. An additive `organization_redemption_claims` table links each organization coordination key and selected weekly reset to its ordinary `redemption_attempts` row, preserving version-1 and version-2 history without a destructive migration.

Provider behavior is why the strict weekly-distance gate exists: production history shows that verified reset consumption normally moves the weekly reset to roughly seven days after consumption, while one historical credit disappeared without a visible weekly-window move. The guardian therefore does not assume every outcome moves the window, verifies post-state, and refuses to risk postponing a natural weekly reset that is 48 hours away or sooner.

Raw access/refresh tokens, broker account IDs, provider credit IDs, Authorization headers, and provider response bodies never enter logs or SQLite. Account and credit identities are stored as SHA-256 references; human-readable broker labels and expiry times remain available to operators. The runner exports only the one broker admin value needed by the guardian, removes the broker's other secret variables before `exec`, and starts the Telegram notifier with only `HOME`, `LANG`, and a fixed system `PATH`; the notifier never inherits broker or OpenAI credentials.

## Warning and redemption timing

Each available, plan-supported `codex_rate_limits` credit is warned once as it crosses each threshold:

- 48 hours
- 24 hours
- 6 hours
- 2 hours
- 1 hour

If the machine was down at a threshold, `Persistent=true` starts the missed timer and the next pass records every crossed-but-unreported threshold. Expiry thresholds are warning deadlines only; they no longer authorize or block automatic redemption. Every 15-minute pass evaluates fresh organization-wide exhaustion, so a qualifying event is handled without an agent process being alive. A credit may be automatically redeemed far outside the old two-hour expiry window, but only under the organization-exhaustion policy above. The separate manual exact-account/expiry command remains unchanged and does not widen automatic authorization.

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
