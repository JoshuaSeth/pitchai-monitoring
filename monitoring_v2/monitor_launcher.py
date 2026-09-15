# Copyright (c) 2026 PitchAI. All rights reserved.
"""Initialize inventory-aware logging before running the established monitor."""

from __future__ import annotations

import argparse
import runpy
from dataclasses import dataclass
from pathlib import Path

from .result_logging import install_result_log_policy


@dataclass
class LauncherArguments(argparse.Namespace):
    """Typed configuration argument shared with the monitor's existing CLI."""

    config: Path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"


def main() -> None:
    """Preserve legacy CLI arguments while installing selected-inventory logging."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path, default=LauncherArguments.config)
    arguments, _ = parser.parse_known_args(namespace=LauncherArguments())
    install_result_log_policy(arguments.config)
    runpy.run_module("domain_checks.main", run_name="__main__")


if __name__ == "__main__":
    main()
