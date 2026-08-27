'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const puppeteer = require('puppeteer');

const BASE_URL = process.env.MONITORING_DASHBOARD_BASE_URL || 'http://127.0.0.1:8111';
const IDENTITY = process.env.MONITORING_DASHBOARD_IDENTITY || 'info@pitchai.net';
const EXPECTED_SHA = process.env.MONITORING_DASHBOARD_EXPECTED_SHA || 'unknown';
const EXPECTED_DOMAINS = Number(process.env.MONITORING_DASHBOARD_EXPECTED_DOMAINS || '62');
const EXPECTED_GROUPS = Number(process.env.MONITORING_DASHBOARD_EXPECTED_GROUPS || '15');
const SCREENSHOT_PATH = '/tmp/monitoring-live-dashboard-proof.png';
const SUMMARY_FETCH_TIMEOUT_MS = 5000;
const REQUIRED_TABS = ['domains', 'databases', 'infrastructure', 'reliability', 'journeys'];
const REQUIRED_UNIMIX_DOMAINS = ['unimixbrasil.com.br', 'www.unimixbrasil.com.br'];

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function phase(name) {
  process.stdout.write('LIVE_DASHBOARD_PHASE=' + name + '\n');
}

async function summaryFromPage(page) {
  return page.evaluate(async (cacheBuster, fetchTimeoutMs) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), fetchTimeoutMs);
    try {
      const response = await fetch('/dashboard/api/v1/monitoring/summary?range=24h&_=' + cacheBuster, {
        credentials: 'same-origin',
        cache: 'no-store',
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('summary HTTP ' + response.status);
      return response.json();
    } finally {
      clearTimeout(timeout);
    }
  }, Date.now(), SUMMARY_FETCH_TIMEOUT_MS);
}

async function waitForUnimixHealth(page) {
  try {
    await page.waitForFunction(async (requiredDomains, fetchTimeoutMs) => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), fetchTimeoutMs);
      try {
        const response = await fetch(
          '/dashboard/api/v1/monitoring/summary?range=24h&_=' + Date.now(),
          {credentials: 'same-origin', cache: 'no-store', signal: controller.signal},
        );
        if (!response.ok) return false;
        const summary = await response.json();
        const domains = Array.isArray(summary.domains) ? summary.domains : [];
        return requiredDomains.every((hostname) => {
          const domain = domains.find((item) => item && item.domain === hostname);
          const last = domain && domain.last && typeof domain.last === 'object' ? domain.last : {};
          return domain && domain.group === 'unimix' && last.ok === true && Number(last.status_code) === 200;
        });
      } catch (error) {
        if (error && error.name !== 'AbortError') throw error;
        return false;
      } finally {
        clearTimeout(timeout);
      }
    }, {timeout: 120000, polling: 2000}, REQUIRED_UNIMIX_DOMAINS, SUMMARY_FETCH_TIMEOUT_MS);
  } catch (error) {
    const summary = await summaryFromPage(page);
    const domains = list(summary.domains)
      .filter((item) => REQUIRED_UNIMIX_DOMAINS.includes(object(item).domain))
      .map((item) => ({domain: object(item).domain, group: object(item).group, last: object(item).last}));
    throw new Error('Unimix health did not converge: ' + JSON.stringify(domains), {cause: error});
  }
}

async function waitForInfrastructureData(page) {
  try {
    await page.waitForFunction(async (fetchTimeoutMs) => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), fetchTimeoutMs);
      try {
        const response = await fetch(
          '/dashboard/api/v1/monitoring/summary?range=24h&_=' + Date.now(),
          {credentials: 'same-origin', cache: 'no-store', signal: controller.signal},
        );
        if (!response.ok) return false;
        const summary = await response.json();
        const dashboards = summary && typeof summary.dashboards === 'object' ? summary.dashboards : {};
        const infrastructure =
          dashboards && typeof dashboards.infrastructure === 'object' ? dashboards.infrastructure : {};
        const containers =
          infrastructure && typeof infrastructure.containers === 'object' ? infrastructure.containers : {};
        const items = Array.isArray(containers.items) ? containers.items : [];
        const counts = containers && typeof containers.counts === 'object' ? containers.counts : {};
        const total = Number(counts.total);
        const restartTotal = Number(containers.restart_total);
        const hasRows =
          containers.data_state === 'available' &&
          items.length > 0 &&
          Number.isInteger(total) &&
          total === items.length;
        const hasSummary =
          containers.data_state === 'summary_only' &&
          items.length === 0 &&
          Number.isInteger(total) &&
          total > 0 &&
          Number.isInteger(restartTotal) &&
          restartTotal >= 0;
        return hasRows || hasSummary;
      } catch (error) {
        if (error && error.name !== 'AbortError') throw error;
        return false;
      } finally {
        clearTimeout(timeout);
      }
    }, {timeout: 120000, polling: 2000}, SUMMARY_FETCH_TIMEOUT_MS);
  } catch (error) {
    const summary = await summaryFromPage(page);
    const infrastructure = object(object(summary.dashboards).infrastructure);
    throw new Error(
      'Infrastructure data did not converge: ' + JSON.stringify(object(infrastructure.containers)),
      {cause: error},
    );
  }
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
    phase('navigate');
    const response = await page.goto(BASE_URL + '/dashboard', {waitUntil: 'networkidle0', timeout: 60000});
    assert.ok(response, 'dashboard navigation returned no response');
    assert.equal(response.status(), 200, 'dashboard navigation failed');
    await page.waitForFunction(() => {
      const note = document.querySelector('#domain-inventory-note');
      return Boolean(note && note.textContent && note.textContent.includes('monitored domains'));
    }, {timeout: 30000});
    phase('wait_unimix');
    await waitForUnimixHealth(page);
    phase('unimix_healthy');
    phase('wait_infrastructure');
    await waitForInfrastructureData(page);
    phase('infrastructure_ready');

    phase('verify_summary_contract');
    const summary = await summaryFromPage(page);
    const domains = list(summary.domains);
    const groups = list(summary.domain_groups);
    const dashboards = object(summary.dashboards);
    const databases = object(dashboards.databases);
    const infrastructure = object(dashboards.infrastructure);
    const reliability = object(dashboards.reliability);
    const journeys = object(dashboards.journeys);
    const dependencies = list(databases.items);
    const containerProjection = object(infrastructure.containers);
    const containerItems = list(containerProjection.items);
    const containerCounts = object(containerProjection.counts);
    const containerTotal = Number(containerCounts.total);
    const containerRestartTotal = Number(containerProjection.restart_total);
    const hasLiveContainerRows =
      containerProjection.data_state === 'available' &&
      containerItems.length > 0 &&
      Number.isInteger(containerTotal) &&
      containerTotal === containerItems.length;
    const hasLiveContainerSummary =
      containerProjection.data_state === 'summary_only' &&
      containerItems.length === 0 &&
      Number.isInteger(containerTotal) &&
      containerTotal > 0 &&
      Number.isInteger(containerRestartTotal) &&
      containerRestartTotal >= 0;
    assert.equal(domains.length, EXPECTED_DOMAINS, 'live domain inventory count changed');
    assert.equal(groups.length, EXPECTED_GROUPS, 'live domain group count changed');
    const unimixGroup = groups.find((group) => object(group).id === 'unimix');
    assert.ok(unimixGroup, 'live dashboard omitted the Unimix customer group');
    assert.equal(Number(object(unimixGroup).enabled), REQUIRED_UNIMIX_DOMAINS.length);
    assert.equal(Number(object(unimixGroup).healthy), REQUIRED_UNIMIX_DOMAINS.length);
    for (const hostname of REQUIRED_UNIMIX_DOMAINS) {
      const domain = domains.find((item) => object(item).domain === hostname);
      assert.ok(domain, 'live dashboard omitted ' + hostname);
      assert.equal(object(domain).group, 'unimix', hostname + ' escaped the Unimix group');
      assert.equal(object(object(domain).last).ok, true, hostname + ' is not healthy');
      assert.equal(Number(object(object(domain).last).status_code), 200, hostname + ' did not return HTTP 200');
      assert.equal(object(object(domain).alert_policy).telegram, 'critical', hostname + ' is not alertable');
    }
    assert.deepEqual(Object.keys(dashboards).sort(), ['databases', 'infrastructure', 'journeys', 'reliability']);
    assert.equal(databases.collector_status, 'healthy', 'database collector is not healthy');
    assert.equal(databases.data_state, 'live', 'database dependency state is not live');
    assert.ok(dependencies.length > 0, 'database dependency inventory is empty');
    assert.equal(object(infrastructure.polling).dashboard_extra_probes, 0, 'dashboard introduced extra infrastructure probes');
    assert.ok(
      hasLiveContainerRows || hasLiveContainerSummary,
      'infrastructure tab has neither current container rows nor a current retained container summary',
    );
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

    phase('verify_tabs');
    const tabs = await verifyTabs(page);
    await page.click('#tab-domains');
    const domainsPanelVisible = await page.$eval(
      '#panel-domains',
      (panel) => !panel.hidden && panel.innerText.trim().length > 0,
    );
    assert.equal(domainsPanelVisible, true, 'domains panel was not visible for Unimix verification');
    phase('verify_unimix_rows');
    await page.click('[data-testid="dash-domain-groups"] button[data-group="unimix"]');
    for (const hostname of REQUIRED_UNIMIX_DOMAINS) {
      const rowText = await page.$eval(`[data-domain="${hostname}"]`, (row) => row.innerText.toLowerCase());
      assert.ok(rowText.includes(hostname), 'rendered dashboard row omitted ' + hostname);
      assert.ok(rowText.includes('healthy'), 'rendered dashboard row is not healthy for ' + hostname);
    }
    phase('verify_database_copy');
    await page.click('#tab-databases');
    const databasePanel = await page.$eval('#panel-databases', (panel) => ({
      hidden: panel.hidden,
      text: panel.innerText.toLowerCase(),
    }));
    assert.equal(databasePanel.hidden, false, 'database panel was not visible for copy verification');
    for (const expected of ['Runtime credentials / grants', 'PgBouncer/tunnel', 'query-permission', 'Credential state']) {
      assert.ok(databasePanel.text.includes(expected.toLowerCase()), 'database panel omitted ' + expected);
    }
    phase('verify_incidents_and_mobile');
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
      unimixDomains: REQUIRED_UNIMIX_DOMAINS,
      unimixHealthy: REQUIRED_UNIMIX_DOMAINS.length,
      tabs,
      incidents: incidentCount,
      databaseDependencies: dependencies.length,
      databaseCollector: databases.collector_status,
      databaseDataState: databases.data_state,
      infrastructureDataState: containerProjection.data_state,
      infrastructureContainers: containerItems.length,
      infrastructureTracked: containerTotal,
      infrastructureRestartTotal: containerRestartTotal,
      reliabilityGroups: list(reliability.groups).length,
      journeys: list(journeys.items).length,
      mobileViewport,
      screenshotSha256,
      receipts,
    };
    phase('complete');
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
