'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const puppeteer = require('puppeteer');

const BASE_URL = process.env.MONITORING_DASHBOARD_BASE_URL || 'http://127.0.0.1:8111';
const IDENTITY = process.env.MONITORING_DASHBOARD_IDENTITY || 'info@pitchai.net';
const EXPECTED_SHA = process.env.MONITORING_DASHBOARD_EXPECTED_SHA || 'unknown';
const EXPECTED_DOMAINS = Number(process.env.MONITORING_DASHBOARD_EXPECTED_DOMAINS || '60');
const EXPECTED_GROUPS = Number(process.env.MONITORING_DASHBOARD_EXPECTED_GROUPS || '14');
const SCREENSHOT_PATH = '/tmp/monitoring-live-dashboard-proof.png';
const REQUIRED_TABS = ['domains', 'databases', 'infrastructure', 'reliability', 'journeys'];

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

async function summaryFromPage(page) {
  return page.evaluate(async () => {
    const response = await fetch('/dashboard/api/v1/monitoring/summary?range=24h', {
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error('summary HTTP ' + response.status);
    return response.json();
  });
}

async function verifyTabs(page) {
  const tabs = await page.$$eval('[data-testid="dash-tabs"] [role="tab"]', (nodes) =>
    nodes.map((node) => node.getAttribute('data-dashboard-tab')),
  );
  assert.deepEqual(tabs, REQUIRED_TABS, 'dashboard tab contract changed');
  for (const tab of REQUIRED_TABS) {
    await page.click('#tab-' + tab);
    const visible = await page.$eval('#panel-' + tab, (panel) => !panel.hidden && panel.innerText.trim().length > 0);
    assert.equal(visible, true, tab + ' tab did not render live data');
  }
  return tabs;
}

async function verifyIncidentDisclosure(page) {
  const count = await page.$$eval('[data-testid="dash-incidents"] .incident__toggle', (nodes) => nodes.length);
  assert.ok(count > 0, 'live dashboard rendered no actionable incident disclosure');
  const selector = '[data-testid="dash-incidents"] .incident__toggle';
  const before = await page.$eval(selector, (node) => node.getAttribute('aria-expanded'));
  await page.click(selector);
  const after = await page.$eval(selector, (node) => node.getAttribute('aria-expanded'));
  assert.notEqual(after, before, 'incident disclosure did not toggle');
  await page.click(selector);
  return count;
}

async function verifyMobileFit(page) {
  await page.setViewport({width: 390, height: 844, deviceScaleFactor: 1});
  const viewport = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  assert.ok(viewport.documentWidth <= viewport.innerWidth, 'document overflowed the 390px viewport');
  assert.ok(viewport.bodyWidth <= viewport.innerWidth, 'body overflowed the 390px viewport');
  return viewport;
}

async function main() {
  const receipts = {consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: []};
  const browser = await puppeteer.launch({
    headless: true,
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    page.on('console', (message) => {
      if (message.type() === 'error') receipts.consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => receipts.pageErrors.push(String(error)));
    page.on('requestfailed', (request) => receipts.failedRequests.push(request.url()));
    page.on('response', (response) => {
      if (response.status() >= 400) receipts.httpErrors.push({url: response.url(), status: response.status()});
    });
    await page.setExtraHTTPHeaders({'x-pitchai-email': IDENTITY});
    await page.setViewport({width: 1440, height: 1000, deviceScaleFactor: 1});
    const response = await page.goto(BASE_URL + '/dashboard', {waitUntil: 'networkidle0', timeout: 60000});
    assert.ok(response, 'dashboard navigation returned no response');
    assert.equal(response.status(), 200, 'dashboard navigation failed');
    await page.waitForFunction(() => {
      const note = document.querySelector('#domain-inventory-note');
      return Boolean(note && note.textContent && note.textContent.includes('monitored domains'));
    }, {timeout: 30000});

    const summary = await summaryFromPage(page);
    const domains = list(summary.domains);
    const groups = list(summary.domain_groups);
    const dashboards = object(summary.dashboards);
    const databases = object(dashboards.databases);
    const infrastructure = object(dashboards.infrastructure);
    const reliability = object(dashboards.reliability);
    const journeys = object(dashboards.journeys);
    const dependencies = list(databases.items);
    assert.equal(domains.length, EXPECTED_DOMAINS, 'live domain inventory count changed');
    assert.equal(groups.length, EXPECTED_GROUPS, 'live domain group count changed');
    assert.deepEqual(Object.keys(dashboards).sort(), ['databases', 'infrastructure', 'journeys', 'reliability']);
    assert.equal(databases.collector_status, 'healthy', 'database collector is not healthy');
    assert.equal(databases.data_state, 'live', 'database dependency state is not live');
    assert.ok(dependencies.length > 0, 'database dependency inventory is empty');
    assert.equal(object(infrastructure.polling).dashboard_extra_probes, 0, 'dashboard introduced extra infrastructure probes');
    assert.ok(list(object(infrastructure.containers).items).length > 0, 'infrastructure tab has no live containers');
    assert.ok(list(reliability.groups).length > 0, 'reliability tab has no live groups');
    assert.ok(list(journeys.items).length > 0, 'journeys tab has no live registry rows');

    const coverage = new Set(dependencies.flatMap((dependency) => list(object(dependency).coverage)));
    for (const expected of ['login/authentication', 'read-only query', 'timeout/reachability']) {
      assert.ok(coverage.has(expected), 'database probe coverage is missing ' + expected);
    }
    assert.ok(
      coverage.has('configured schema grants') || coverage.has('schema usage'),
      'database probe coverage is missing schema/grant checks',
    );
    assert.ok(
      coverage.has('configured table/materialized-view grants') || coverage.has('configured table permission'),
      'database probe coverage is missing relation/permission checks',
    );

    const tabs = await verifyTabs(page);
    await page.click('#tab-databases');
    const databaseText = await page.$eval('#panel-databases', (panel) => panel.innerText);
    for (const expected of ['Runtime credentials / grants', 'PgBouncer/tunnel', 'query-permission', 'Credential state']) {
      assert.ok(databaseText.includes(expected), 'database panel omitted ' + expected);
    }
    const incidentCount = await verifyIncidentDisclosure(page);
    const mobileViewport = await verifyMobileFit(page);
    await page.$eval('#panel-databases', (panel) => panel.scrollIntoView());
    await page.screenshot({path: SCREENSHOT_PATH});
    const screenshotSha256 = crypto.createHash('sha256').update(fs.readFileSync(SCREENSHOT_PATH)).digest('hex');
    assert.deepEqual(receipts, {consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: []});

    const proof = {
      capturedAt: new Date().toISOString(),
      deploymentSha: EXPECTED_SHA,
      status: response.status(),
      title: await page.title(),
      domains: domains.length,
      groups: groups.length,
      tabs,
      incidents: incidentCount,
      databaseDependencies: dependencies.length,
      databaseCollector: databases.collector_status,
      databaseDataState: databases.data_state,
      infrastructureContainers: list(object(infrastructure.containers).items).length,
      reliabilityGroups: list(reliability.groups).length,
      journeys: list(journeys.items).length,
      mobileViewport,
      screenshotSha256,
      receipts,
    };
    process.stdout.write('LIVE_DASHBOARD_PROOF=' + JSON.stringify(proof) + '\n');
  } finally {
    await browser.close();
    if (fs.existsSync(SCREENSHOT_PATH)) fs.unlinkSync(SCREENSHOT_PATH);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
