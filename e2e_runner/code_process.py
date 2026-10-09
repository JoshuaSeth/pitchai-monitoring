# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated code runner command, environment and bounded result parsing."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast

from domain_checks.browser_failure import BrowserFailure

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject, JsonValue

    from .job_result import JobRequest

RESULT_PREFIX = "E2E_RESULT_JSON="
_RESULT_LINE = re.compile(r"^E2E_RESULT_JSON=(\{.*\})\s*$")


def extract_result_json(text: str) -> JsonObject | None:
    """Return the last complete result object, without falling back to an earlier match."""
    if not text:
        return None
    last = None
    for line in str(text).splitlines():
        match = _RESULT_LINE.match(line.strip())
        if match:
            last = match.group(1)
    if not last:
        return None
    with suppress(Exception):
        data = cast("JsonValue", json.loads(last))
        return data if isinstance(data, dict) else None
    return None


def sandbox_environment(request: JobRequest, directory: Path, home: str) -> dict[str, str]:
    """Return the existing explicit environment allowlist plus a private temporary HOME."""
    keys = {"PATH", "LANG", "TZ", "CHROMIUM_PATH", "NODE_PATH", "PUPPETEER_EXECUTABLE_PATH", "PUPPETEER_SKIP_DOWNLOAD"}
    environment: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in keys or key.startswith(("LC_", "PUPPETEER_")):
            environment[str(key)] = str(value)
    environment["HOME"] = home
    environment["BASE_URL"] = str(request.base_url)
    environment["ARTIFACTS_DIR"] = str(directory)
    return environment


@dataclass(frozen=True)
class CodeProcess:
    """Own only one submitted test process and its disposable home directory."""

    request: JobRequest
    test_file: Path
    directory: Path
    trace: bool

    def command(self) -> list[str]:
        """Return the original interpreter and ordered arguments for either code kind.

        Raises:
            RuntimeError: The caller passed an unsupported test kind.
        """
        kind = self.request.kind
        if kind == "playwright_python":
            command = [sys.executable, "-m", "e2e_sandbox.playwright_python"]
        elif kind == "puppeteer_js":
            script = Path(__file__).resolve().parent.parent / "e2e_sandbox" / "puppeteer_js_runner.js"
            command = ["node", str(script)]
        else:
            message = f"unsupported_code_kind: {kind}"
            raise RuntimeError(message)
        command.extend(["--test-file", str(self.test_file), "--base-url", str(self.request.base_url),
                        "--artifacts-dir", str(self.directory), "--timeout-seconds", str(self.request.timeout)])
        if kind == "playwright_python" and self.trace:
            command.append("--trace-on-failure")
        return command

    async def run(self) -> tuple[JsonObject | None, str]:
        """Return parsed output after native execution; errors and cancellation propagate.

        The private HOME addresses the old shared-temporary-directory exposure.
        No caller environment or submitted artifact directory is removed.

        Raises:
            RuntimeError: The process boundary returned neither a result nor an error.
        """
        command = self.command()
        with TemporaryDirectory(prefix="pitchai-e2e-home-") as home:
            environment = sandbox_environment(self.request, self.directory, home)
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment,
            )
            with BrowserFailure() as failure:
                output, errors = await asyncio.wait_for(
                    process.communicate(), timeout=max(5.0, float(self.request.timeout) + 15.0),
                )
                stdout = (output or b"").decode("utf-8", errors="replace")
                stderr = (errors or b"").decode("utf-8", errors="replace")
                combined = f"{stdout.strip()}\n{stderr.strip()}".strip()
                return extract_result_json(f"{stdout}\n{stderr}"), combined
            with suppress(Exception):
                process.kill()
            if failure.error is not None:
                raise failure.error
        message = "Process observation ended without output or an error"
        raise RuntimeError(message)
