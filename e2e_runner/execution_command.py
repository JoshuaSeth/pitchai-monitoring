# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command construction for submitted-code sandbox entry points."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e2e_runner.execution_models import CodeExecutionRequest


def execution_command(*, request: CodeExecutionRequest) -> list[str]:
    """Build the declared sandbox command for a submitted test.

    Returns:
        The executable and arguments for the requested code-test kind.

    Raises:
        ValueError: If the code-test kind has no sandbox entry point.
    """
    if request.kind == "playwright_python":
        command = [
            sys.executable,
            "-m",
            "e2e_sandbox.playwright_python",
            "--test-file",
            str(request.test_file),
            "--base-url",
            request.base_url,
            "--artifacts-dir",
            str(request.artifacts_dir),
            "--timeout-seconds",
            str(request.timeout_seconds),
        ]
        if request.trace_on_failure:
            command.append("--trace-on-failure")
        return command
    if request.kind == "puppeteer_js":
        javascript_runner = (
            Path(__file__).resolve().parent.parent
            / "e2e_sandbox"
            / "puppeteer_js_runner.js"
        )
        return [
            "node",
            str(javascript_runner),
            "--test-file",
            str(request.test_file),
            "--base-url",
            request.base_url,
            "--artifacts-dir",
            str(request.artifacts_dir),
            "--timeout-seconds",
            str(request.timeout_seconds),
        ]
    message = f"unsupported code test kind: {request.kind}"
    raise ValueError(message)
