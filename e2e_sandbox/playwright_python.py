# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command-line adapter for the submitted Playwright Python sandbox."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import cast

from e2e_sandbox.models import SandboxRequest
from e2e_sandbox.runtime import execute_submission

RESULT_PREFIX = "E2E_RESULT_JSON="


def _parse_request(argv: list[str]) -> SandboxRequest:
    parser = argparse.ArgumentParser(description="Run a submitted Playwright Python test file.")
    _ = parser.add_argument("--test-file", required=True)
    _ = parser.add_argument("--base-url", required=True)
    _ = parser.add_argument("--artifacts-dir", required=True)
    _ = parser.add_argument("--timeout-seconds", type=float, default=45.0)
    _ = parser.add_argument("--trace-on-failure", action="store_true")
    namespace = parser.parse_args(argv)
    timeout_seconds = cast("float", namespace.timeout_seconds)
    if timeout_seconds <= 0:
        message = "--timeout-seconds must be positive"
        raise ValueError(message)
    test_file = Path(cast("str", namespace.test_file)).resolve(strict=True)
    artifacts_dir = Path(cast("str", namespace.artifacts_dir)).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return SandboxRequest(
        test_file=test_file,
        base_url=cast("str", namespace.base_url).strip(),
        artifacts_dir=artifacts_dir,
        timeout_seconds=timeout_seconds,
        trace_on_failure=cast("bool", namespace.trace_on_failure),
    )


def main() -> None:
    """Execute the sandbox command and emit its structured result.

    Raises:
        SystemExit: Always, with the submitted test outcome.
    """
    _ = os.environ.setdefault("HOME", tempfile.gettempdir())
    request = _parse_request(sys.argv[1:])
    with asyncio.Runner() as runner:
        result = runner.run(execute_submission(request))
    _ = sys.stdout.write(RESULT_PREFIX + result.to_json() + "\n")
    _ = sys.stdout.flush()
    raise SystemExit(0 if result.status == "pass" else 1)


if __name__ == "__main__":
    main()
