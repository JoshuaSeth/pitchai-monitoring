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
- Optional: additional reliability/uptime signals (separate from domain UP/DOWN):
  - SLO error-budget burn rate (multi-window burn rules)
  - TLS certificate expiry / handshake failures
  - DNS resolution + optional drift detection
  - RED / golden signals over rolling windows (error-rate + latency percentiles)
  - API contract checks (per-domain JSON endpoint assertions)
  - Synthetic transactions (Playwright step flows)
  - Core Web Vitals (LCP/CLS/INP approximation)
  - Docker container health (unhealthy/not running/restarting/OOM)
  - Reverse proxy upstream/failover signals (upstream headers + optional Nginx logs)
  - Meta-monitoring (cycle overruns/state write failures)

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
  - Rolling history:
    - `history.retention_days`
  - SLO burn rate:
    - `slo.enabled`, `slo.target_percent`, `slo.burn_rate_rules`
  - TLS:
    - `tls.enabled`, `tls.min_days_valid`, `tls.interval_minutes`
  - DNS:
    - `dns.enabled`, `dns.resolvers`, `dns.alert_on_drift`
  - RED/golden signals:
    - `red.enabled`, `red.window_minutes`, `red.error_rate_max_percent`, `red.http_p95_ms_max`, `red.browser_p95_ms_max`
  - API contract checks (per-domain):
    - `api_contract.enabled` and per-domain `CHECK.api_contract_checks`
  - Synthetic transactions (per-domain):
    - `synthetic.enabled` and per-domain `CHECK.synthetic_transactions`
  - Web vitals:
    - `web_vitals.enabled` and per-domain `CHECK.web_vitals` (optional overrides)
  - Container health:
    - `container_health.enabled` (requires mounting `/var/run/docker.sock`)
  - Proxy/upstream signals:
    - `proxy.enabled` and per-domain `CHECK.proxy` (optional)
  - Meta-monitoring:
    - `meta_monitoring.enabled`

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
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/log/nginx:/var/log/nginx:ro \
  -e TELEGRAM_BOT_TOKEN=... \
  -e TELEGRAM_CHAT_ID=... \
  -e PITCHAI_DISPATCH_TOKEN=... \
  -e STATE_PATH="/data/state.json" \
  service-monitoring:latest
```

## External E2E Registry (Developer-Submitted Test Files)

This repo also includes an optional external E2E test registry + runner:

- Registry service: `python -m e2e_registry.server` (FastAPI + minimal UI)
- Runner worker: `python -m e2e_runner.main` (claims due runs and executes uploaded Playwright-Python / Puppeteer-JS tests, plus legacy StepFlow)

The registry stores tests + run history in SQLite (single-host) by default and stores artifacts on a shared volume.

Colleague-facing onboarding guide (UI + API copy/paste): `docs/external-e2e-tests-colleague-guide.md`

### What External Developers Upload

1. Playwright (Python): a single `.py` file that defines:

```py
async def run(page, base_url, artifacts_dir):
    await page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded")
    title = await page.title()
    assert "Example" in (title or "")
```

2. Puppeteer (JS): a single `.js`/`.mjs` file that exports:

```js
module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  await page.goto(String(baseUrl || "").replace(/\\/$/, "") + "/", { waitUntil: "domcontentloaded" });
  const title = await page.title();
  if (!String(title || "").includes("Example")) {
    throw new Error("title_missing: Example");
  }
};
```

Both types can write additional artifacts into `artifacts_dir` if desired. On failures, the sandbox runners will try to capture `failure.png` + `run.log`.

### Run Locally (3 terminals)

1. Start the registry:

```bash
export E2E_REGISTRY_DB_PATH="/tmp/e2e-registry.db"
export E2E_ARTIFACTS_DIR="/tmp/e2e-artifacts"
export E2E_TESTS_DIR="/tmp/e2e-tests"
export E2E_REGISTRY_ADMIN_TOKEN="admin-..."
export E2E_REGISTRY_MONITOR_TOKEN="monitor-..."
export E2E_REGISTRY_RUNNER_TOKEN="runner-..."
python -m e2e_registry.server
```

2. Start the runner:

```bash
export E2E_REGISTRY_BASE_URL="http://127.0.0.1:8111"
export E2E_REGISTRY_RUNNER_TOKEN="runner-..."
export E2E_ARTIFACTS_DIR="/tmp/e2e-artifacts"
export E2E_TESTS_DIR="/tmp/e2e-tests"
python -m e2e_runner.main
```

3. Upload a test file via API:

```bash
TENANT_API_KEY="..."

curl -sS -X POST "http://127.0.0.1:8111/api/v1/tests/upload" \
  -H "Authorization: Bearer ${TENANT_API_KEY}" \
  -F "name=my_home_smoke" \
  -F "base_url=https://deplanbook.com" \
  -F "kind=playwright_python" \
  -F "interval_seconds=300" \
  -F "timeout_seconds=45" \
  -F "jitter_seconds=30" \
  -F "down_after_failures=2" \
  -F "up_after_successes=2" \
  -F "file=@./my_home_smoke.py"
```

4. (Optional) Include external E2E summary in heartbeats:

```bash
export E2E_REGISTRY_BASE_URL="http://127.0.0.1:8111"
export E2E_REGISTRY_MONITOR_TOKEN="monitor-..."
python -m domain_checks.main --once
```

Spec and API details: `specs/external-e2e-tests-registry.md`

## Monitoring Dashboard (monitoring.pitchai.net)

The `e2e-registry` service also serves a monitoring dashboard for the main uptime/signal monitor:

- Dashboard UI: `/dashboard`
- Backing API: `/api/v1/monitoring/*`

The dashboard reads `state.json` from the `service-monitoring-state` docker volume (mounted read-only into the `e2e-registry` container).

Auth:

- By default the dashboard requires the `E2E_REGISTRY_MONITOR_TOKEN` (or `E2E_REGISTRY_ADMIN_TOKEN`) via `/dashboard/login`.
- This is intentionally separate from tenant API keys (external developers should not see internal monitoring signals).

## Live Tests (Real Domains / Real Services)

This repo includes `pytest.mark.live` tests that hit real external domains and/or the real Dispatcher/E2E registry. They are skipped by default and require explicit env flags:

- Live domain + metric checks (real websites):
  - `RUN_LIVE_TESTS=1 python -m pytest -m live tests/test_live_domains.py tests/test_live_metrics.py`
- Live Dispatcher smoke test (real agent run):
  - `RUN_LIVE_DISPATCH_TESTS=1 python -m pytest -m live tests/test_live_dispatch.py`
- Live E2E registry acceptance tests (real registry + runner + Playwright):
  - `RUN_LIVE_E2E_REGISTRY_TESTS=1 python -m pytest -m live tests/test_live_e2e_registry_prod.py`

## Add a domain

1. Add an entry to `domain_checks/config.yaml`.
2. Create `domain_checks/<domain>/check.py` using stable selectors (prefer ids/meta/script tags) and an `expected_title_contains` when available.
