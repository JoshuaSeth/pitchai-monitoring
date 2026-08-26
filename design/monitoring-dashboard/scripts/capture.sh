#!/usr/bin/env bash
set -euo pipefail

workspace_root="$(git rev-parse --show-toplevel)"
design_root="$workspace_root/design/monitoring-dashboard"
server_port="8877"
python_bin="${DESIGN_PYTHON_BIN:-$workspace_root/.venv/bin/python}"
server_log="${TMPDIR:-/tmp}/pitchai-monitoring-design-server.log"

"$python_bin" -m http.server "$server_port" --bind 127.0.0.1 --directory "$design_root" >"$server_log" 2>&1 &
server_pid="$!"
trap 'kill "$server_pid" 2>/dev/null || true' EXIT

DESIGN_ROOT="$design_root" SERVER_PORT="$server_port" "$python_bin" - <<'PY'
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright


async def capture() -> None:
    design_root = Path(os.environ["DESIGN_ROOT"])
    port = os.environ["SERVER_PORT"]
    output_dir = design_root / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = (
        "concept-01-incidents",
        "concept-03-infrastructure",
        "concept-04-reliability",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=("--no-sandbox",),
        )
        context = await browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        for page_name in pages:
            page = await context.new_page()
            await page.goto(f"http://127.0.0.1:{port}/renders/{page_name}.html", wait_until="networkidle")
            await page.evaluate("window.scrollTo(0, 0)")
            await page.screenshot(path=output_dir / f"{page_name}.png", full_page=False)
            await page.close()
        await context.close()
        await browser.close()


asyncio.run(capture())
PY

printf 'Captured monitoring concepts in %s/screenshots\n' "$design_root"
