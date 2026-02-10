# PitchAI Monitoring: API Guide for Adding E2E UI Checks (Upload Real Test Files)

This monitoring system continuously runs **real end-to-end UI checks** (not just HTTP 200) against our deployed sites and alerts when behavior breaks.

The goal: every important service must have at least 1-3 E2E tests registered here so we catch UI regressions immediately.

Public UI/API entrypoint:

- `https://monitoring.pitchai.net/`

Important: colleagues register tests **via API** by uploading the actual Playwright/Puppeteer test file. The web UI exists only as an optional viewer/debugger.

## Why This Matters (What You Are Expected To Do)

- If your service has a UI, you must contribute a small set of E2E monitoring tests that always pass.
- Monitoring runs these tests continuously (typically every 5 minutes) against production, and alerts when behavior regresses.
- This catches UI breakages that still return HTTP 200 (wrong page, broken rendering, missing buttons, auth flow broken, etc.).

## What You Need

1. An **E2E Registry API key** (tenant API key).
   - If you do not have one, ask Seth/Infra to create a tenant + API key for your project/team.
2. A single test file in one of these formats:
   - Playwright (Python) `*.py`
   - Puppeteer (JavaScript) `*.js` or `*.mjs`

Important: tests must be **non-destructive** (read-only). They must not disrupt production services.

## Fastest Path (Recommended): API Quickstart (Copy/Paste)

All API calls use:

- `Authorization: Bearer <YOUR_TENANT_API_KEY>`

You can use `jq` to extract fields, but it is optional.

### 1) Upload Your Test File (Registers It For Continuous Monitoring)

Playwright Python:

```bash
API_KEY="..."      # ask Seth/Infra
BASE_URL="https://autopar.pitchai.net"

TEST_ID="$(
  curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_home_smoke" \
    -F "base_url=${BASE_URL}" \
    -F "kind=playwright_python" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.py" \
  | jq -r '.test.id'
)"

echo "TEST_ID=${TEST_ID}"
```

Puppeteer JS:

```bash
API_KEY="..."      # ask Seth/Infra
BASE_URL="https://autopar.pitchai.net"

TEST_ID="$(
  curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_home_smoke_js" \
    -F "base_url=${BASE_URL}" \
    -F "kind=puppeteer_js" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.js" \
  | jq -r '.test.id'
)"

echo "TEST_ID=${TEST_ID}"
```

If you do not have `jq`, extract the ID with Python instead:

```bash
TEST_ID="$(
  curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_home_smoke" \
    -F "base_url=${BASE_URL}" \
    -F "kind=playwright_python" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.py" \
  | python -c 'import json,sys; print(json.load(sys.stdin)[\"test\"][\"id\"])'
)"
```

### 2) Run It Immediately (Don’t Wait For The Scheduler)

```bash
curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/run" \
  -H "Authorization: Bearer ${API_KEY}"
```

### 3) Check Result (Pass/Fail + Artifacts)

```bash
curl -fsSL "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/runs?limit=5" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

On failure, common artifacts include:

- `failure.png` (screenshot)
- `run.log` (structured error + traceback/stack)
- Playwright Python only (optional): `trace.zip` when tracing is enabled server-side for that run

Artifacts can be downloaded by name:

```bash
RUN_ID="..."          # from /runs response
ARTIFACT_NAME="run.log"

curl -fsSL -o "${ARTIFACT_NAME}" \
  "https://monitoring.pitchai.net/api/v1/runs/${RUN_ID}/artifacts/${ARTIFACT_NAME}" \
  -H "Authorization: Bearer ${API_KEY}"
```

### 4) Replace/Update The Test File (Keep Same TEST_ID)

```bash
curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/source" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "file=@./new_version.py"
```

### 5) Temporarily Disable Noisy/Flaky Tests (So They Stop Alerting)

Disable (with an optional `until`):

```bash
curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/disable" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"reason":"temporary_disable: flaky upstream auth provider","until":"2026-02-20"}'
```

Re-enable:

```bash
curl -fsSL -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/enable" \
  -H "Authorization: Bearer ${API_KEY}"
```

### 6) Adjust Schedule / Timeouts / Debounce Without Re-uploading The File

```bash
curl -fsSL -X PATCH "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"interval_seconds":300,"timeout_seconds":60,"down_after_failures":3,"up_after_successes":2}'
```

## Optional: Web UI (Viewer Only)

1. Open `https://monitoring.pitchai.net/ui/login`
2. Paste your API key
3. Go to `Upload Test`
4. Fill in:
   - `Base URL` (the site you are checking, e.g. `https://autopar.pitchai.net`)
   - `Kind` (Playwright Python or Puppeteer JS)
   - `Interval seconds` (default `300` is typical)
   - Select your test file
5. Click `Create test`
6. Open the created test and click `Run now`
7. Confirm:
   - A passing test shows `pass`
   - A failing test shows `fail` and has artifacts (screenshot/log) you can open in the run detail page

Replacing a test file (no need to create a new test):

1. Open the test detail page
2. Use `Replace file`
3. Click `Run now` again

Temporarily disabling noisy/flaky tests:

1. Open the test detail page
2. Click `Disable` with a reason (and optionally an `until` timestamp/date)

## Writing Tests

### Playwright Python Test Template (`*.py`)

Your file must define:

- `async def run(page, base_url, artifacts_dir): ...`

Example "homepage smoke test":

```py
async def run(page, base_url, artifacts_dir):
    url = base_url.rstrip("/") + "/"
    await page.goto(url, wait_until="domcontentloaded")

    # Assert something stable and meaningful.
    title = await page.title()
    assert "AutoPAR" in (title or "")

    # Prefer stable selectors (ids, data-testid, consistent links).
    await page.wait_for_selector("text=Login", timeout=30_000)
```

### Puppeteer JS Test Template (`*.js` / `*.mjs`)

Your file must export:

- `run({ page, baseUrl, artifactsDir })`

Example:

```js
module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  const url = String(baseUrl || "").replace(/\\/$/, "") + "/";
  await page.goto(url, { waitUntil: "domcontentloaded" });

  const title = await page.title();
  if (!String(title || "").includes("AutoPAR")) {
    throw new Error("title_missing: AutoPAR");
  }

  await page.waitForSelector("text/Login", { timeout: 30_000 });
};
```

## What Makes a Good Monitoring Test (Operational Rules)

- Assert something stable:
  - A meaningful title + a stable UI element (`data-testid`, a stable link, a navbar item)
- Use explicit waits:
  - `wait_for_selector(..., timeout=30_000)` instead of arbitrary sleeps
- Keep it short:
  - Target runtime: under 5-15 seconds
- Keep it read-only:
  - Do not create/delete real data in production
  - Do not spam login endpoints or expensive workflows
- When you must authenticate:
  - Use a dedicated test account with least privilege
  - If the test requires secrets, coordinate with Infra first (do not hardcode credentials in the test file)

## What Happens When It Fails

- The system debounces failures (default: needs multiple consecutive failures to alert).
- When a test transitions from OK to FAIL, the registry sends a Telegram alert with links to:
  - the failing run
  - its artifacts (screenshot/log)
- Optional: failures can dispatch a read-only investigation agent (if enabled for that test).

## Reference

- Spec: `specs/external-e2e-tests-registry.md`
- OpenAPI: `https://monitoring.pitchai.net/openapi.json`
