# Copyright (c) 2026 PitchAI. All rights reserved.
"""Uploaded source fixtures and configuration for live registry tests."""

PASSING_SOURCE = """async def run(page, base_url, artifacts_dir):
    await page.goto(base_url.rstrip('/') + '/', wait_until='domcontentloaded')
    title = await page.title()
    if 'Deplanbook' not in (title or ''):
        raise AssertionError('expected Deplanbook page title')
    await page.wait_for_selector('a[href="/diary"]', state='visible', timeout=30000)
"""
FAILING_SOURCE = r"""module.exports.run = async ({ page, baseUrl, artifactsDir }) => {
  await page.goto(String(baseUrl || '').replace(/\/$/, '') + '/', { waitUntil: 'domcontentloaded' });
  const body = await page.evaluate(() => document.body?.innerText || '');
  if (!String(body || '').includes('THIS SHOULD NOT EXIST')) {
    throw new Error('text_missing: THIS SHOULD NOT EXIST');
  }
};
"""
COMMON_CONFIG = {
    "interval_seconds": 3600,
    "timeout_seconds": 35,
    "jitter_seconds": 0,
    "down_after_failures": 20,
    "up_after_successes": 20,
    "notify_on_recovery": False,
    "dispatch_on_failure": False,
}
