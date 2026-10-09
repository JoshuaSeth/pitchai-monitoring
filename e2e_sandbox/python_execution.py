# Copyright (c) 2026 PitchAI. All rights reserved.
"""Prepared submission execution and its original post-start cleanup boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .python_result import RunFailureBoundary

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from .python_browser import BrowserSession
    from .python_module import EntryPoint, MainEntry, RunEntry
    from .python_result import RunResult


@dataclass(frozen=True)
class PreparedSubmission:
    """Original timestamp, module identity and invocation arguments for one run."""

    started: float
    base_url: str
    artifacts_dir: Path
    timeout_ms: int
    module: ModuleType
    entry: EntryPoint

    async def run(self, session: BrowserSession) -> RunResult:
        """Close resources after result handling, preserving ordinary-error tolerance.

        Returns:
            The observed result; cancellation still propagates through cleanup.
        """
        try:
            return await self.observe(session)
        finally:
            await session.close()

    async def observe(self, session: BrowserSession) -> RunResult:
        """Keep run-over-main selection and await only actual coroutine results.

        Returns:
            Existing success or ordinary failure result.

        Raises:
            RuntimeError: The invocation returned without a result or an error.
        """
        result = None
        failure = RunFailureBoundary()
        with failure:
            if getattr(self.module, "run", None) is self.entry:
                run = cast("RunEntry", self.entry)
                outcome = run(session.page, self.base_url, str(self.artifacts_dir))
            else:
                main = cast("MainEntry", self.entry)
                outcome = main(self.base_url, str(self.artifacts_dir))
            if asyncio.iscoroutine(outcome):
                _ = await outcome
            result = await session.success(self.started, {})
        if failure.error is not None:
            return await session.failure(self.started, self.artifacts_dir, failure.error, failure.traceback_text)
        if result is None:
            message = "submitted_test_did_not_produce_a_result"
            raise RuntimeError(message)
        return result
