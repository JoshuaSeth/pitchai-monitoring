# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native runner configuration, including the existing poll and concurrency bounds."""

from __future__ import annotations

import os
from contextlib import suppress
from typing import NamedTuple


def env_int(name: str, default: int) -> int:
    """Return the configured integer or the original malformed-string fallback."""
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    with suppress(ValueError):
        return int(str(raw).strip())
    return int(default)


def env_bool(name: str, *, default: bool) -> bool:
    """Return a recognized environment boolean, otherwise the supplied default."""
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


class RunnerConfig(NamedTuple):
    """The native runner's eight existing configuration fields."""

    registry_base_url: str
    runner_token: str
    artifacts_dir: str
    tests_dir: str
    poll_seconds: float
    concurrency: int
    trace_on_failure: bool
    code_exec_mode: str


def load_config() -> RunnerConfig:
    """Read native settings without performing IO or resolving a browser.

    Returns:
        Existing defaults, normalized mode and bounded poll/concurrency values.
    """
    base = (os.getenv("E2E_REGISTRY_BASE_URL") or "http://127.0.0.1:8111").strip()
    token = (os.getenv("E2E_REGISTRY_RUNNER_TOKEN") or "").strip()
    artifacts = (os.getenv("E2E_ARTIFACTS_DIR") or "/data/e2e-artifacts").strip()
    tests_dir = (os.getenv("E2E_TESTS_DIR") or "/tests").strip()
    poll = float(os.getenv("E2E_RUNNER_POLL_SECONDS") or "5")
    concurrency = env_int("E2E_RUNNER_CONCURRENCY", 1)
    trace = env_bool("E2E_RUNNER_TRACE_ON_FAILURE", default=False)
    mode = (os.getenv("E2E_RUNNER_CODE_EXEC_MODE") or "local").strip().lower()
    if mode not in {"local", "docker"}:
        mode = "local"
    return RunnerConfig(base, token, artifacts, tests_dir, max(0.5, poll),
                        max(1, min(concurrency, 10)), trace, mode)
