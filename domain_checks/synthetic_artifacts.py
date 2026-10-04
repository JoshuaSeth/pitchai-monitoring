# Copyright (c) 2026 PitchAI. All rights reserved.
"""Optional synthetic browser artifacts, preserving the existing failure boundaries."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .browser_failure import BrowserFailure
from .synthetic_values import safe_str

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page

    from .event_bus_delivery import JsonObject


def write_artifact(path: str, content: str) -> None:
    """Keep optional artifact IO failures from changing a transaction result."""
    with suppress(Exception):
        # Normalize lexically; resolving symlinks would change the original writer contract.
        destination = Path(os.path.normpath(Path(path).absolute()))
        destination.parent.mkdir(parents=True, exist_ok=True)
        _ = destination.write_text(content, encoding="utf-8")


@dataclass
class SyntheticArtifacts:
    """Own the optional trace flag and original artifact-name dictionary."""

    directory: str | None
    names: dict[str, str] = field(default_factory=dict)
    tracing_started: bool = False

    async def start(self, context: BrowserContext, *, enabled: bool) -> None:
        """Begin a trace only when requested with an output directory."""
        if enabled and self.directory:
            with suppress(Exception):
                await context.tracing.start(screenshots=True, snapshots=True, sources=False)
                self.tracing_started = True

    async def capture(self, page: Page, filename: str, key: str) -> None:
        """Record an artifact name only after its screenshot call succeeds."""
        if self.directory:
            with suppress(Exception):
                _ = await page.screenshot(path=str(Path(self.directory) / filename), full_page=True)
                self.names[key] = filename

    async def finish(self, context: BrowserContext) -> None:
        """Stop successful traces without exporting them."""
        if self.tracing_started:
            with suppress(Exception):
                await context.tracing.stop()

    async def failure(self, page: Page | None, context: BrowserContext | None) -> None:
        """Capture the original failure screenshot and attempt trace export once."""
        if page is not None:
            await self.capture(page, "failure.png", "failure_screenshot")
        if self.tracing_started and context is not None and self.directory:
            with BrowserFailure() as export:
                await context.tracing.stop(path=str(Path(self.directory) / "trace.zip"))
                self.names["trace_zip"] = "trace.zip"
            if export.error is not None:
                with suppress(Exception):
                    await context.tracing.stop()

    def write_failure(self, fields: JsonObject) -> None:
        """Retain the original bounded log and its name even after an optional IO error."""
        if self.directory:
            content = safe_str(json.dumps(fields, ensure_ascii=False, sort_keys=True, indent=2), max_len=50_000)
            write_artifact(str(Path(self.directory) / "run.log"), content)
            self.names.setdefault("run_log", "run.log")
