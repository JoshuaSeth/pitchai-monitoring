# Copyright (c) 2026 PitchAI. All rights reserved.
"""Command-line entry point for the E2E runner service."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import cast

from e2e_registry.storage_permissions import validate_migrated_storage
from e2e_runner.config import load_config
from e2e_runner.recovery import recover_interrupted_submissions
from e2e_runner.service import run_forever, run_once
from e2e_runner.uid_lease_config import require_declared_shared_lease_directory

_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


@dataclass(frozen=True)
class CliOptions:
    """Validated command-line options."""

    once: bool


def _parse_options() -> CliOptions:
    parser = argparse.ArgumentParser(
        description="Execute claimed PitchAI E2E registry jobs.",
    )
    _ = parser.add_argument(
        "--once",
        action="store_true",
        help="Execute one claimed batch and exit",
    )
    namespace = parser.parse_args()
    return CliOptions(once=cast("bool", namespace.once))


def _configure_logging() -> None:
    configured_level = (
        os.getenv("E2E_RUNNER_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))
        .strip()
        .upper()
    )
    level = _LOG_LEVELS.get(configured_level)
    if level is None:
        message = f"Unsupported E2E_RUNNER_LOG_LEVEL: {configured_level}"
        raise ValueError(message)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _run(options: CliOptions) -> int:
    config = load_config()
    _ = require_declared_shared_lease_directory()
    await asyncio.to_thread(
        validate_migrated_storage,
        tests_directory=config.tests_dir,
        artifacts_directory=config.artifacts_dir,
    )
    await recover_interrupted_submissions(config.artifacts_dir)
    if options.once:
        return await run_once(config)
    await run_forever(config)
    return 0


def main() -> None:
    """Run the E2E runner command-line process.

    Raises:
        SystemExit: Always, with the process exit code.
    """
    _configure_logging()
    options = _parse_options()
    with asyncio.Runner() as runner:
        exit_code = runner.run(_run(options))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
