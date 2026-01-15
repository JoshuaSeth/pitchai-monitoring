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

## Configuration

- `domain_checks/config.yaml`
- Per-domain checks: `domain_checks/<domain>/check.py` (must define `CHECK = {...}`)

## Environment

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `PITCHAI_DISPATCH_TOKEN`
- Optional: `PITCHAI_DISPATCH_BASE_URL` (default `https://dispatch.pitchai.net`)
- Optional: `PITCHAI_DISPATCH_MODEL` (e.g. `gpt-5.2-medium`, `gpt-5.2-high`)
- Optional: `CHROMIUM_PATH` (inside Docker: `/usr/bin/chromium`)

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
  -e TELEGRAM_BOT_TOKEN=... \
  -e TELEGRAM_CHAT_ID=... \
  -e PITCHAI_DISPATCH_TOKEN=... \
  service-monitoring:latest
```

## Add a domain

1. Add an entry to `domain_checks/config.yaml`.
2. Create `domain_checks/<domain>/check.py` using stable selectors (prefer ids/meta/script tags) and an `expected_title_contains` when available.
