# ASTRA model-availability watch

`python -m astra_model_watch` checks every directory-backed account in the
authentication broker independently. It rereads each root-owned `auth.json` on
every pass, uses only `tokens.access_token`, derives the ChatGPT account header
with the broker's signed-claim precedence, and refuses an identity mismatch.
Disabled and quota-limited accounts are still catalog-checked when their
existing authentication is valid because catalog visibility is separate from
generation capacity.

An account that the broker explicitly marks `auth_invalid` is no longer a
logged-in account. It is recorded on every cycle as unavailable, is never
refreshed or queried with its known-invalid bearer, and automatically rejoins
catalog checks if the broker later restores valid authentication.

## Provider boundary

The only allowed provider operation is:

```text
GET https://chatgpt.com/backend-api/codex/models?client_version=<installed Codex version>
```

This is the model-list request implemented by the Codex client. The monitor
sends no body, follows no redirects, uses no cookie or proxy, retries only on
the next scheduled pass, and has no token-refresh implementation. Its URL
validator permits only the HTTPS `chatgpt.com` origin, exact model-catalog path,
and single `client_version` query key. Reset, credit, consume, redeem, claim,
activate, OAuth, lease, response-generation, task, usage, and WHAM paths are
outside the transport's capability.

## Two-hour operator run

Run as root on `pitchai-dev`:

```bash
./ops/run_astra_model_watch.sh
```

The launcher fixes the interval at 300 seconds and duration at 7,200 seconds.
The watch samples at the start and again at the two-hour boundary, for 25
cycles. It requires a verified requester-private Telegram preflight before the
window begins and alerts `seth-ori` only if a new ASTRA match appears.

Logs and the hashed alert-deduplication ledger live under
`/mnt/pitchai-dev-data/monitoring/auth-broker-astra-model-watch`, which must
remain mode 0700. Each JSONL
event is fsynced to a mode-0600 append-only file and includes timestamps,
account label/fingerprint, enabled and broker availability state, auth source,
model count, ASTRA matches, sanitized errors, provider request count, and the
code-enforced reset-safety assertion. Tokens and response bodies are never
logged.

The launcher also pins temporary and cache paths under
`/mnt/pitchai-dev-data/scratch/auth-broker-astra-model-watch`; it does not
materialize an environment, build, cache, or output on the production root
filesystem.

A one-cycle network validation is available but is not two-hour proof:

```bash
python3 -m astra_model_watch \
  --once \
  --client-version 0.153.1 \
  --log-path /mnt/pitchai-dev-data/monitoring/auth-broker-astra-model-watch/validation.jsonl \
  --alert-state-path /mnt/pitchai-dev-data/monitoring/auth-broker-astra-model-watch/alert-state.json \
  --notify-command ./ops/astra_model_watch_notifier.sh
```

The finite watch exits nonzero on an unexpected account-check failure, an
account-registry change, a cycle starting over 30 seconds late, private alert
delivery failure, or an incomplete observation window. Broker-declared
`auth_invalid` sessions are preserved in coverage evidence as unavailable
rather than misreported as logged-in catalog checks.

## Unattended five-minute watch

The production timer runs one bounded pass every five minutes. Each invocation
revalidates the requester-private Telegram route, rereads the broker inventory,
checks each currently authenticated account once, and exits. It sends nothing
when ASTRA is absent. A newly observed ASTRA model triggers one private alert
to `seth-ori`; the hashed delivery ledger suppresses repeats across later timer
invocations while retaining a failed delivery for retry.

The deployed code lives under
`/mnt/pitchai-dev-data/services/auth-broker-astra-model-watch/current`. Runtime
state, the stable JSONL audit log, console output, temporary files, and cache
all remain under `/mnt/pitchai-dev-data`. The systemd and logrotate definitions
are the only host-root configuration. The timer never keeps a bearer token or
Python process resident between passes. The deployed launcher pins the verified
Codex catalog compatibility version at `0.153.1`, the release that backported
the GPT-6-Astra catalog entry. Older versions can return a successful but stale
catalog with Astra omitted. Each timer pass therefore does not execute Codex or
materialize a Codex home/cache merely to discover the version.

Inspect the scheduler without starting an extra pass:

```bash
systemctl status pitchai-astra-model-watch.timer --no-pager
systemctl list-timers pitchai-astra-model-watch.timer --no-pager
```

Run one bounded production-equivalent pass:

```bash
systemctl start pitchai-astra-model-watch.service
```
