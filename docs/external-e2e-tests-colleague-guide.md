# PitchAI Monitoring: Colleague Guide (API Upload of Real E2E Test Files)

This guide explains, step by step, how to register your own real UI test in monitoring using API calls only.

- Public endpoint: `https://monitoring.pitchai.net`
- OpenAPI: `https://monitoring.pitchai.net/openapi.json`
- Primary workflow: upload your real `.py` or `.js`/`.mjs` file through API

## Why You Should Do This

Our uptime checks already verify HTTP + UI expectations.  
Your custom E2E checks add service-specific behavior validation, so we catch regressions that still return 200.

Examples of what these tests catch:

- Login button disappeared
- Dashboard page renders but key table is missing
- Redirect loops or wrong landing page

## Before You Start

You need:

1. A tenant API key (`Authorization: Bearer <API_KEY>`)
2. `curl`
3. Optional but recommended: `jq`

If you do not have an API key yet, ask Seth/Infra.

## Mandatory Domain & Scope Rules (Read First)

These are required for all submitted monitoring tests:

1. `base_url` must be the **main production domain** of the app.
   - Good: `https://deplanbook.com`, `https://autopar.pitchai.net`, `https://cms.deplanbook.com`
   - Not allowed: staging/dev URLs, local URLs, raw server IPs, private/internal hostnames
2. Your test must validate real user-visible behavior on that main domain (not only a 200 response).
3. If you have alias/redirect domains, use one of these patterns:
   - Primary test on canonical main domain (recommended)
   - Optional extra test for alias redirect behavior (e.g. alias redirects to canonical domain)
4. Keep tests non-destructive and safe for production traffic.

Minimum expectation per app:

- At least 1 main-domain smoke test
- At least 1 critical-path test (key flow/UI element for your app)

## Step 1: Create Your Test File

Use one of these two supported formats.

### Option A: Playwright Python (`.py`)

Your file must define:

- `async def run(page, base_url, artifacts_dir): ...`

Example file `autopar_home_smoke.py`:

```python
async def run(page, base_url, artifacts_dir):
    url = base_url.rstrip("/") + "/login-page"
    await page.goto(url, wait_until="domcontentloaded")

    title = await page.title()
    assert "AutoPAR" in (title or "")

    await page.wait_for_selector("text=Login", timeout=30_000)
```

### Option B: Puppeteer JavaScript (`.js` or `.mjs`)

Your file must export:

- `run({ page, baseUrl, artifactsDir })`

Example file `autopar_home_smoke.js`:

```javascript
module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  const url = String(baseUrl || "").replace(/\/$/, "") + "/login-page";
  await page.goto(url, { waitUntil: "domcontentloaded" });

  const title = await page.title();
  if (!String(title || "").includes("AutoPAR")) {
    throw new Error("title_missing: AutoPAR");
  }

  await page.waitForSelector("text/Login", { timeout: 30000 });
};
```

## Step 2: Upload the File (Creates a Monitoring Test)

Set variables once:

```bash
BASE="https://monitoring.pitchai.net"
API_KEY="PASTE_YOUR_API_KEY_HERE"
MAIN_DOMAIN_URL="https://autopar.pitchai.net"   # MUST be canonical production app domain
```

### Upload Playwright Python file

```bash
RESP="$(
  curl -fsSL -X POST "$BASE/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_home_smoke_py" \
    -F "base_url=${MAIN_DOMAIN_URL}" \
    -F "kind=playwright_python" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.py"
)"

echo "$RESP" | jq .
TEST_ID="$(echo "$RESP" | jq -r '.test.id')"
echo "TEST_ID=$TEST_ID"
```

### Upload Puppeteer JS file

```bash
RESP="$(
  curl -fsSL -X POST "$BASE/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_home_smoke_js" \
    -F "base_url=${MAIN_DOMAIN_URL}" \
    -F "kind=puppeteer_js" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.js"
)"

echo "$RESP" | jq .
TEST_ID="$(echo "$RESP" | jq -r '.test.id')"
echo "TEST_ID=$TEST_ID"
```

If you do not have `jq`, extract with Python:

```bash
TEST_ID="$(echo "$RESP" | python -c 'import json,sys; print(json.load(sys.stdin)["test"]["id"])')"
```

## Step 3: Run Immediately (Don’t Wait for Scheduler)

```bash
curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/run" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

## Step 4: Check Latest Runs

```bash
curl -fsSL "$BASE/api/v1/tests/${TEST_ID}/runs?limit=5" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

What to look for:

- `status: "pass"` means success
- `status: "fail"` means your test assertion failed
- `status: "infra_degraded"` means browser/runtime infra issue (not necessarily your app)

## Step 5: Download Failure Artifacts (Screenshot / Log)

1. Read latest run ID:

```bash
RUN_ID="$(
  curl -fsSL "$BASE/api/v1/tests/${TEST_ID}/runs?limit=1" \
    -H "Authorization: Bearer ${API_KEY}" \
  | jq -r '.runs[0].id'
)"
echo "RUN_ID=$RUN_ID"
```

2. Download `run.log`:

```bash
curl -fsSL -o run.log \
  "$BASE/api/v1/runs/${RUN_ID}/artifacts/run.log" \
  -H "Authorization: Bearer ${API_KEY}"
```

3. Download screenshot if present:

```bash
curl -fsSL -o failure.png \
  "$BASE/api/v1/runs/${RUN_ID}/artifacts/failure.png" \
  -H "Authorization: Bearer ${API_KEY}"
```

## Step 6: Replace the File (Keep Same Test ID)

Use this when your test script needs fixing.  
This updates source code for the same monitoring test.

```bash
curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/source" \
  -H "Authorization: Bearer ${API_KEY}" \
  -F "file=@./autopar_home_smoke_v2.py" \
  | jq .
```

Run again after replacing:

```bash
curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/run" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

## Step 7: Temporarily Disable a Noisy Test

Disable with reason and optional end date:

```bash
curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/disable" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"reason":"temporary flake while upstream is unstable","until":"2026-02-20"}' \
  | jq .
```

Enable again:

```bash
curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/enable" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

## Step 8: Change Frequency / Timeout / Debounce

```bash
curl -fsSL -X PATCH "$BASE/api/v1/tests/${TEST_ID}" \
  -H "Authorization: Bearer ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "interval_seconds": 300,
    "timeout_seconds": 60,
    "down_after_failures": 3,
    "up_after_successes": 2
  }' \
  | jq .
```

Recommended defaults:

- `interval_seconds`: `300` (every 5 minutes)
- `timeout_seconds`: `45` to `60`
- `down_after_failures`: `2` (or `3` for flaky upstreams)
- `up_after_successes`: `2`

## Full End-to-End Example (Copy/Paste)

This shows the complete flow in one go (upload → run → inspect):

```bash
BASE="https://monitoring.pitchai.net"
API_KEY="PASTE_YOUR_API_KEY_HERE"
MAIN_DOMAIN_URL="https://autopar.pitchai.net"

cat > autopar_home_smoke.py <<'PY'
async def run(page, base_url, artifacts_dir):
    await page.goto(base_url.rstrip("/") + "/login-page", wait_until="domcontentloaded")
    title = await page.title()
    assert "AutoPAR" in (title or "")
    await page.wait_for_selector("text=Login", timeout=30000)
PY

RESP="$(
  curl -fsSL -X POST "$BASE/api/v1/tests/upload" \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "name=autopar_quickstart_example" \
    -F "base_url=${MAIN_DOMAIN_URL}" \
    -F "kind=playwright_python" \
    -F "interval_seconds=300" \
    -F "timeout_seconds=45" \
    -F "jitter_seconds=30" \
    -F "down_after_failures=2" \
    -F "up_after_successes=2" \
    -F "file=@./autopar_home_smoke.py"
)"

TEST_ID="$(echo "$RESP" | jq -r '.test.id')"
echo "Created TEST_ID=$TEST_ID"

curl -fsSL -X POST "$BASE/api/v1/tests/${TEST_ID}/run" \
  -H "Authorization: Bearer ${API_KEY}" >/dev/null

sleep 5

curl -fsSL "$BASE/api/v1/tests/${TEST_ID}/runs?limit=3" \
  -H "Authorization: Bearer ${API_KEY}" \
  | jq .
```

## Rules for Safe Monitoring Tests

Your submitted tests must be:

- On the app’s canonical production main domain (`base_url`)
- Read-only and non-destructive
- Short (target under 5-15 seconds)
- Stable (use reliable selectors and clear assertions)
- Production-safe (no high-volume loops, no destructive write flows)

If credentials are needed, use dedicated low-privilege test accounts and coordinate with Infra.

## What a “Good” Main-Domain Monitoring Test Looks Like

A high-quality test usually does all of this:

1. Starts at the main production domain (`base_url`)
2. Waits for meaningful UI render (not just network idle)
3. Asserts one stable identity signal (title, product text, or logo area)
4. Asserts one stable critical element (login button, dashboard link, main CTA, key nav item)
5. Fails clearly with actionable error message if expectation is broken

This gives us fast and reliable signal that the app is truly usable for end users.

## Troubleshooting

### `401 Unauthorized`

- API key missing/invalid, or wrong `Authorization: Bearer ...` format.

### `400 invalid_kind`

- `kind` must be `playwright_python` or `puppeteer_js`.

### `400 python_test_must_be_.py` / `400 puppeteer_test_must_be_.js`

- File extension must match selected `kind`.

### Test always fails

- Download `run.log` and `failure.png` artifacts and fix selectors/assertions.
- Ensure `base_url` points to the app’s canonical production main domain.

### Test marked `infra_degraded`

- Usually browser runtime instability, not a direct application assertion failure.
- Re-run once; if repeated, share `run.log` with Infra.

## Optional UI (Viewer / Manual Debug)

You can still inspect tests and runs in the UI:

- Login: `https://monitoring.pitchai.net/ui/login`
- Tests list: `https://monitoring.pitchai.net/ui/tests`

API upload remains the primary required workflow.
