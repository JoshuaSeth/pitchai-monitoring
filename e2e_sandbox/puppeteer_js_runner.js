#!/usr/bin/env node

/* eslint-disable no-console */

const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const RESULT_PREFIX = "E2E_RESULT_JSON=";

function safeStr(x, maxLen = 2000) {
  const s = String(x ?? "");
  return s.length <= maxLen ? s : s.slice(0, maxLen);
}

function writeText(p, content) {
  try {
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, content, { encoding: "utf8" });
  } catch (_) {}
}

function parseArgs(argv) {
  const out = {
    testFile: "",
    baseUrl: "",
    artifactsDir: "",
    timeoutSeconds: 45,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--test-file") out.testFile = String(argv[++i] ?? "");
    else if (a === "--base-url") out.baseUrl = String(argv[++i] ?? "");
    else if (a === "--artifacts-dir") out.artifactsDir = String(argv[++i] ?? "");
    else if (a === "--timeout-seconds") out.timeoutSeconds = Number(argv[++i] ?? "45");
  }
  if (!out.testFile || !out.baseUrl || !out.artifactsDir) {
    throw new Error("missing_required_args");
  }
  return out;
}

function isBrowserInfraError(err) {
  const msg = String((err && (err.message || err)) || "");
  const s = msg.toLowerCase();
  return (
    s.includes("target closed") ||
    s.includes("browser has disconnected") ||
    s.includes("session closed") ||
    s.includes("protocol error") ||
    s.includes("page crashed") ||
    s.includes("target crashed") ||
    s.includes("navigation failed because browser has disconnected")
  );
}

async function loadTestModule(testFile) {
  // Prefer CommonJS require(), but fall back to ESM dynamic import when needed.
  try {
    // eslint-disable-next-line import/no-dynamic-require, global-require
    return require(testFile);
  } catch (e) {
    const u = pathToFileURL(testFile).href;
    return await import(u);
  }
}

function pickEntry(mod) {
  if (mod && typeof mod.run === "function") return mod.run;
  if (mod && mod.default && typeof mod.default.run === "function") return mod.default.run;
  if (mod && typeof mod.default === "function") return mod.default;
  if (mod && typeof mod.main === "function") return mod.main;
  throw new Error("test_file_must_export_run_or_default");
}

async function main() {
  process.env.HOME = process.env.HOME || "/tmp";
  const args = parseArgs(process.argv.slice(2));

  const artifactsDir = path.resolve(args.artifactsDir);
  fs.mkdirSync(artifactsDir, { recursive: true });

  const startedAt = Date.now();
  let browser = null;
  let page = null;
  let result = null;
  try {
    const puppeteer = require("puppeteer");
    const executablePath = process.env.PUPPETEER_EXECUTABLE_PATH || "/usr/bin/chromium";
    browser = await puppeteer.launch({
      headless: true,
      executablePath,
      args: [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--no-first-run",
        "--no-default-browser-check",
      ],
    });
    page = await browser.newPage();
    page.setDefaultTimeout(Math.max(1, Math.floor(Number(args.timeoutSeconds) * 1000)));

    const mod = await loadTestModule(path.resolve(args.testFile));
    const entry = pickEntry(mod);

    // Preferred contract: `module.exports.run = async ({ page, baseUrl, artifactsDir }) => { ... }`
    const maybe = entry({ page, baseUrl: args.baseUrl, artifactsDir });
    if (maybe && typeof maybe.then === "function") await maybe;

    const elapsedMs = Date.now() - startedAt;
    const finalUrl = page ? safeStr(page.url(), 2000) : null;
    let title = null;
    try {
      title = page ? safeStr(await page.title(), 500) : null;
    } catch (_) {
      title = null;
    }
    result = {
      status: "pass",
      elapsed_ms: Math.round(elapsedMs * 1000) / 1000,
      error_kind: null,
      error_message: null,
      final_url: finalUrl,
      title,
      artifacts: {},
      browser_infra_error: false,
    };
  } catch (err) {
    const infra = isBrowserInfraError(err);
    const status = infra ? "infra_degraded" : "fail";
    const elapsedMs = Date.now() - startedAt;

    let finalUrl = null;
    let title = null;
    try {
      finalUrl = page ? safeStr(page.url(), 2000) : null;
    } catch (_) {}
    try {
      title = page ? safeStr(await page.title(), 500) : null;
    } catch (_) {}

    const artifacts = {};
    try {
      if (page) {
        const fn = "failure.png";
        await page.screenshot({ path: path.join(artifactsDir, fn), fullPage: true });
        artifacts.failure_screenshot = fn;
      }
    } catch (_) {}

    try {
      writeText(
        path.join(artifactsDir, "run.log"),
        JSON.stringify(
          {
            status,
            error_kind: err && err.name ? String(err.name) : "Error",
            error_message: safeStr(err && err.message ? err.message : err, 2000),
            final_url: finalUrl,
            title,
            browser_infra_error: infra,
            stack: safeStr(err && err.stack ? err.stack : "", 50000),
          },
          null,
          2
        )
      );
      artifacts.run_log = "run.log";
    } catch (_) {}

    result = {
      status,
      elapsed_ms: Math.round(elapsedMs * 1000) / 1000,
      error_kind: err && err.name ? String(err.name) : "Error",
      error_message: safeStr(err && err.message ? err.message : err, 2000),
      final_url: finalUrl,
      title,
      artifacts,
      browser_infra_error: infra,
    };
  } finally {
    try {
      if (page) await page.close();
    } catch (_) {}
    try {
      if (browser) await browser.close();
    } catch (_) {}
  }

  process.stdout.write(RESULT_PREFIX + JSON.stringify(result) + "\n");
  process.stdout.flush?.();
  process.exit(result && result.status === "pass" ? 0 : 1);
}

main().catch((e) => {
  const msg = safeStr(e && e.message ? e.message : e, 2000);
  const res = {
    status: "fail",
    elapsed_ms: null,
    error_kind: e && e.name ? String(e.name) : "Error",
    error_message: msg,
    final_url: null,
    title: null,
    artifacts: {},
    browser_infra_error: false,
  };
  process.stdout.write(RESULT_PREFIX + JSON.stringify(res) + "\n");
  process.exit(1);
});

