# PitchAI Service Monitoring

Minute-by-minute uptime + “correct page” monitoring for PitchAI domains.

## What it does

- Every `interval_seconds` (default 60s), checks each configured domain:
  - HTTP GET: status 2xx/3xx and does not look like maintenance/gateway
  - Browser: Playwright renders the page and verifies expected title/selectors/text
- When a domain transitions UP → DOWN (or is DOWN at startup), sends Telegram:
  - `{domain} is DOWN`
- When a domain transitions UP → DOWN, also queues a Codex investigation via PitchAI Dispatcher:
  - Polls until completion and forwards the agent’s final report to Telegram.
- Optional: on a schedule (e.g. `07:30` and `12:00`), sends a heartbeat message that includes per-domain response times.
- Optional: proactive warnings (separate from domain UP/DOWN):
  - Host health thresholds (disk/mem/swap/cpu/load)
  - Per-domain performance thresholds (HTTP ms / Browser ms)
  - These produce separate Telegram warnings and can queue a read-only Dispatcher triage.

## Configuration

- `domain_checks/config.yaml`
- Per-domain checks: `domain_checks/<domain>/check.py` (must define `CHECK = {...}`)
  - Heartbeats:
    - `heartbeat.enabled`: enable/disable scheduled heartbeats
    - `heartbeat.timezone`: timezone name (e.g. `Europe/Amsterdam`, `UTC`)
    - `heartbeat.times`: list of `HH:MM` times (in `heartbeat.timezone`)
  - Temporarily disable a domain (skip checks + alerts):
    - `disabled: true` (or `enabled: false`)
    - `disabled_until`: unix timestamp or ISO-8601 datetime/date (optional)
    - `disabled_reason`: shown in heartbeats/logs (optional)
  - `check_concurrency`: max concurrent domain checks (HTTP + browser) to reduce load spikes / false positives
  - `browser_concurrency`: max concurrent Playwright page checks (lower if Chromium is unstable)
  - Alerting debounce (reduces transient false positives):
    - `alerting.down_after_failures`: consecutive failing cycles required before a DOWN alert is sent
    - `alerting.up_after_successes`: consecutive successful cycles required to mark the domain UP again
  - Host health warnings (do NOT mark any domain down):
    - `host_health.enabled`
    - `host_health.disk_used_percent_max`, `mem_used_percent_max`, `swap_used_percent_max`, `cpu_used_percent_max`
    - `host_health.load1_per_cpu_max` (set `null` to disable)
    - `host_health.down_after_failures` / `up_after_successes` (debounce)
    - `host_health.dispatch_on_degraded` (queue Dispatcher triage)
  - Performance warnings (do NOT mark any domain down):
    - `performance.enabled`
    - `performance.http_elapsed_ms_max`, `performance.browser_elapsed_ms_max`
    - `performance.per_domain_overrides` (optional map: domain → threshold overrides)
    - `performance.down_after_failures` / `up_after_successes` (debounce)
    - `performance.dispatch_on_degraded` (queue Dispatcher triage)

## Environment

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `PITCHAI_DISPATCH_TOKEN`
- Optional: `PITCHAI_DISPATCH_BASE_URL` (default `https://dispatch.pitchai.net`)
- Optional: `PITCHAI_DISPATCH_MODEL` (e.g. `gpt-5.2-medium`, `gpt-5.2-high`)
- Optional: `CHROMIUM_PATH` (inside Docker: `/usr/bin/chromium`)
- Optional: `STATE_PATH` (default `/data/state.json`) to persist UP/DOWN state across restarts

## Run locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export PITCHAI_DISPATCH_TOKEN=...
python -m domain_checks.main --once
```

## Docker

```bash
docker build -t service-monitoring:latest .
docker run --rm \
  -v service-monitoring-state:/data \
  -e TELEGRAM_BOT_TOKEN=... \
  -e TELEGRAM_CHAT_ID=... \
  -e PITCHAI_DISPATCH_TOKEN=... \
  -e STATE_PATH="/data/state.json" \
  service-monitoring:latest
```

## Add a domain

1. Add an entry to `domain_checks/config.yaml`.
2. Create `domain_checks/<domain>/check.py` using stable selectors (prefer ids/meta/script tags) and an `expected_title_contains` when available.
