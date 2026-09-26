# Copyright (c) 2026 PitchAI. All rights reserved.
"""Forward the uv entrypoint to native and existing Python aggregates."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from .ios_quality.runtime import ProcessRunner


def main() -> int:
    """Execute both aggregates and preserve a failure from either one.

    Returns:
        The first failed aggregate status, or zero when both pass.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="List configured Apple gates")
    mode.add_argument("--probe", action="store_true", help="Verify deliberate failing fixtures")
    arguments = parser.parse_args()
    target = "check"
    if cast("bool", arguments.list):
        target = "check-list"
    elif cast("bool", arguments.probe):
        target = "check-probe"
    native_status = ProcessRunner.run(("make", target), cwd=Path.cwd())
    python_status = 0
    if target == "check":
        python_status = ProcessRunner.run(
            ("uv", "run", "--project", "quality", "--python", "3.12.12", "--frozen", "check"),
            cwd=Path.cwd(),
        )
    return native_status or python_status


if __name__ == "__main__":
    raise SystemExit(main())
