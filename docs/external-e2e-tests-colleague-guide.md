# PitchAI Monitoring: Colleague Guide for Adding E2E UI Checks (Upload Real Test Files)

This monitoring system continuously runs **real end-to-end UI checks** (not just HTTP 200) against our deployed sites and alerts when behavior breaks.

The goal: every important service must have at least 1-3 E2E tests registered here so we catch UI regressions immediately.

Public UI/API entrypoint:

- `https://monitoring.pitchai.net/`

## What You Need

1. An **E2E Registry API key** (tenant API key).
   - If you do not have one, ask Seth/Infra to create a tenant + API key for your project/team.
2. A single test file in one of these formats:
   - Playwright (Python) `*.py`
   - Puppeteer (JavaScript) `*.js` or `*.mjs`

Important: tests must be **non-destructive** (read-only). They must not disrupt production services.

## Fastest Path (Recommended): Use The Web UI

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

## API Usage (Copy/Paste)

All API calls use:

- `Authorization: Bearer <YOUR_TENANT_API_KEY>`

### Upload a New Test File

Playwright Python:

```bash
API_KEY="..."

curl -sS -X POST "https://monitoring.pitchai.net/api/v1/tests/upload" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "name=autopar_home_smoke" \
  -F "base_url=https://autopar.pitchai.net" \
  -F "kind=playwright_python" \
  -F "interval_seconds=300" \
  -F "timeout_seconds=45" \
  -F "jitter_seconds=30" \
  -F "down_after_failures=2" \
  -F "up_after_successes=2" \
  -F "file=@./autopar_home_smoke.py"
```

Puppeteer JS:

```bash
API_KEY="..."

curl -sS -X POST "https://monitoring.pitchai.net/api/v1/tests/upload" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "name=autopar_home_smoke_js" \
  -F "base_url=https://autopar.pitchai.net" \
  -F "kind=puppeteer_js" \
  -F "interval_seconds=300" \
  -F "timeout_seconds=45" \
  -F "jitter_seconds=30" \
  -F "down_after_failures=2" \
  -F "up_after_successes=2" \
  -F "file=@./autopar_home_smoke.js"
```

### Run A Test Immediately

```bash
API_KEY="..."
TEST_ID="..."

curl -sS -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/run" \
  -H "Authorization: Bearer ${API_KEY}"
```

### Replace/Update The Test File (Keep The Same TEST_ID)

```bash
API_KEY="..."
TEST_ID="..."

curl -sS -X POST "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/source" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "file=@./new_version.py"
```

### List Recent Runs

```bash
API_KEY="..."
TEST_ID="..."

curl -sS "https://monitoring.pitchai.net/api/v1/tests/${TEST_ID}/runs?limit=20" \
  -H "Authorization: Bearer ${API_KEY}"
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
