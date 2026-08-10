# Codex reset-credit guardian

The reset-credit guardian protects every redeemable Codex rate-limit reset credit held by the authentication broker. It reads broker-managed ChatGPT OAuth state, records warning thresholds, and, in the final two hours, uses the same backend reset-credit endpoint as the Codex app-server. It never reads or spends an OpenAI API key.

Production project task: `AUTH-BROKER-RESET-AUTOMATION-20260810`.

## Safety contract

One production pass performs these steps for every broker account, including disabled or currently reserved accounts:

1. `POST /v1/admin/accounts/{account}/analytics-probe` makes the broker validate or refresh its own OAuth state and persist redacted provider analytics.
2. `GET /v1/admin/accounts/{account}/auth.json` exports the latest broker-owned auth state into process memory. Only `tokens.access_token` and `tokens.account_id` are used. `OPENAI_API_KEY`, if present in that file, is ignored.
3. Direct authenticated reads of `/wham/usage` and `/wham/rate-limit-reset-credits` obtain the authoritative usage state, every opaque credit ID, status, and expiry. The broker's redacted cached count is not trusted for redemption decisions.
4. For a credit inside the two-hour horizon, the full broker probe/export/provider-read sequence is repeated. The service proceeds only if the same exact credit ID is still available with a future expiry.
5. `POST /wham/rate-limit-reset-credits/consume` receives both a durable idempotency key and that exact credit ID. The service never issues an untargeted consume request, so a racing operator cannot cause it to fall through to another credit.
6. A final broker-managed refresh proves whether that exact credit remains available. `reset` and `already_redeemed` count as success only when the post-state confirms the credit is absent or no longer redeemable. Ambiguous transports reuse the same SQLite-backed idempotency key after restart.

The provider can return `nothing_to_reset` when no usage window is exhausted. That outcome does not consume the credit. The guardian records it and tries again on the next 15-minute pass until the credit is handled or expires.

Raw access/refresh tokens, broker account IDs, provider credit IDs, Authorization headers, and provider response bodies never enter logs or SQLite. Account and credit identities are stored as SHA-256 references; human-readable broker labels and expiry times remain available to operators.

## Warning and redemption timing

Each available, plan-supported `codex_rate_limits` credit is warned once as it crosses each threshold:

- 48 hours
- 24 hours
- 6 hours
- 2 hours
- 1 hour

If the machine was down at a threshold, `Persistent=true` starts the missed timer and the next pass records every crossed-but-unreported threshold. Starting at two hours before expiry, every 15-minute pass performs the mandatory fresh recheck and may attempt the exact credit. Fifteen minutes is deliberately more frequent than the requested two-hour cadence so a transient broker/provider failure still leaves several retries.

Production warnings, account-check failures, verified redemptions, and verification failures use the canonical requester-private Telegram route `seth-ori`. There is no group route in the service configuration. Every decision and notification result is also durable in SQLite and journald.

## Production installation

Run from the repository root on `pitchai-dev` as root:

```bash
./ops/deploy_auth_reset_guardian.sh
```

The deployment:

- fingerprints the exact source and installs an immutable release below `/opt/pitchai-auth-reset-guardian/releases/`;
- atomically points `/opt/pitchai-auth-reset-guardian/current` at that release;
- reads the broker secret only from `/etc/auth-token-server/auth-token-server.env` at run time;
- validates the canonical Telegram helper's requester-private Seth route;
- passes an isolated fake-expiry simulation and a live no-consume dry-run;
- installs and enables `pitchai-auth-reset-guardian.timer`;
- starts one immediate live pass and verifies the persistent audit database.

The systemd timer runs on each UTC quarter-hour, survives reboots, and catches missed calendar runs. Its service is a locked one-shot, so overlapping invocations cannot make concurrent consume decisions.

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
- `redemption_attempts`: stable idempotency keys, outcomes, and verification;
- `notifications`: requester-private notification attempts and their status.

Example read-only SQL:

```bash
sqlite3 -readonly /var/lib/pitchai-auth-reset-guardian/audit.sqlite3 \
  "SELECT occurred_at, account_label, event_type, severity, expires_at FROM events ORDER BY event_id DESC LIMIT 50;"
```

## Dry-run and simulation

A live dry-run performs broker refreshes and provider reads. For a due credit it also performs the second fresh recheck, but it never sends a consume request or Telegram notification:

```bash
/usr/local/sbin/pitchai-auth-reset-guardian run --dry-run --no-notify
```

The deterministic fixture exercises warnings, exact-credit targeting, fake redemption, and post-state verification without credentials or network access:

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
python3 -m pytest -q tests/test_auth_reset_guardian.py
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

Remove `--dry-run --no-notify` only after reviewing the fresh-recheck event. The live command uses the same idempotent exact-ID path and post-state verification as automation. Never use an untargeted consume call while multiple credits exist.

## First live handling

The first target is Info's credit expiring `2026-08-11T21:08:33.778745Z`. The expected automatic horizon begins at `2026-08-11T19:08:33.778745Z`. The separate manual broker lane remains active as an observer and emergency backstop; it has been instructed not to issue an untargeted consume. Completion requires monitoring the guardian's first real attempt through an authoritative post-state and sending Seth requester-private proof.
