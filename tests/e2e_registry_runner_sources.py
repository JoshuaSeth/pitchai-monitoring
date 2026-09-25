# Copyright (c) 2026 PitchAI. All rights reserved.
"""Submitted source fixtures for local registry/runner integration."""

PASSING_PYTHON_SOURCE = """import os
from pathlib import Path

async def run(page, base_url, artifacts_dir):
    del artifacts_dir
    if os.geteuid() == 0:
        raise RuntimeError('submitted Python test retained root identity')
    process_status = Path('/proc/self/status').read_text(encoding='utf-8')
    if 'NoNewPrivs:\\t1' not in process_status:
        raise RuntimeError('submitted Python test lacks no-new-privileges')
    url = base_url.rstrip('/') + '/ok'
    await page.goto(url, wait_until='domcontentloaded')
    body = await page.evaluate("() => document.body?.innerText || ''")
    if 'Everything is fine' not in (body or ''):
        raise RuntimeError('expected page text is missing')
"""
FAILING_JAVASCRIPT_SOURCE = r"""const fs = require('fs');

module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  void artifactsDir;
  if (process.getuid() === 0) throw new Error('submitted JS test retained root identity');
  const status = fs.readFileSync('/proc/self/status', 'utf8');
  if (!status.includes('NoNewPrivs:\t1')) throw new Error('submitted JS test lacks no-new-privileges');
  const url = String(baseUrl || '').replace(/\/$/, '') + '/ok';
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  const body = await page.evaluate(() => document.body?.innerText || '');
  if (!String(body || '').includes('THIS SHOULD NOT EXIST')) {
    throw new Error('text_missing: THIS SHOULD NOT EXIST');
  }
};
"""
RECOVERED_JAVASCRIPT_SOURCE = r"""const fs = require('fs');

module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  void artifactsDir;
  if (process.getuid() === 0) throw new Error('submitted JS test retained root identity');
  const status = fs.readFileSync('/proc/self/status', 'utf8');
  if (!status.includes('NoNewPrivs:\t1')) throw new Error('submitted JS test lacks no-new-privileges');
  const url = String(baseUrl || '').replace(/\/$/, '') + '/ok';
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  const body = await page.evaluate(() => document.body?.innerText || '');
  if (!String(body || '').includes('Everything is fine')) {
    throw new Error('text_missing: Everything is fine');
  }
};
"""
