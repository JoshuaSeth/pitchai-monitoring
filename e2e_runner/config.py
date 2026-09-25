# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict environment parsing for the E2E runner."""

from __future__ import annotations

import os
import re
from pathlib import Path

from e2e_runner.models import RunnerConfig

_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "n", "off"})
_MINIMUM_POLL_SECONDS = 0.5
_MAXIMUM_CONCURRENCY = 10
_INTEGER_PATTERN = re.compile(r"[+-]?\d+")
_FLOAT_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _environment_text(name: str, default: str | None = None) -> str:
    raw_value = os.getenv(name)
    value = default if raw_value is None else raw_value
    if value is None or not value.strip():
        message = f"Missing {name}"
        raise ValueError(message)
    return value.strip()


def _environment_integer(name: str, default: int) -> int:
    text = os.getenv(name, str(default)).strip()
    if _INTEGER_PATTERN.fullmatch(text) is None:
        message = f"{name} must be an integer"
        raise ValueError(message)
    return int(text)


def _environment_float(name: str, default: float) -> float:
    text = os.getenv(name, str(default)).strip()
    if _FLOAT_PATTERN.fullmatch(text) is None:
        message = f"{name} must be numeric"
        raise ValueError(message)
    return float(text)


def _environment_boolean(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    message = f"{name} must be a boolean"
    raise ValueError(message)


def load_config() -> RunnerConfig:
    """Load and validate runner configuration from the process environment.

    Returns:
        A fully validated runner configuration.

    Raises:
        ValueError: If a configured value is missing or invalid.
    """
    execution_mode = _environment_text("E2E_RUNNER_CODE_EXEC_MODE", "local").lower()
    if execution_mode != "local":
        message = "E2E_RUNNER_CODE_EXEC_MODE must be 'local'; Docker execution is not implemented"
        raise ValueError(message)

    poll_seconds = _environment_float("E2E_RUNNER_POLL_SECONDS", 5.0)
    if poll_seconds < _MINIMUM_POLL_SECONDS:
        message = "E2E_RUNNER_POLL_SECONDS must be at least 0.5"
        raise ValueError(message)
    concurrency = _environment_integer("E2E_RUNNER_CONCURRENCY", 1)
    if not 1 <= concurrency <= _MAXIMUM_CONCURRENCY:
        message = "E2E_RUNNER_CONCURRENCY must be between 1 and 10"
        raise ValueError(message)

    return RunnerConfig(
        registry_base_url=_environment_text("E2E_REGISTRY_BASE_URL", "http://127.0.0.1:8111"),
        runner_token=_environment_text("E2E_REGISTRY_RUNNER_TOKEN"),
        artifacts_dir=Path(_environment_text("E2E_ARTIFACTS_DIR", "/data/e2e-artifacts")),
        tests_dir=Path(_environment_text("E2E_TESTS_DIR", "/tests")),
        poll_seconds=poll_seconds,
        concurrency=concurrency,
        trace_on_failure=_environment_boolean("E2E_RUNNER_TRACE_ON_FAILURE", default=False),
    )
