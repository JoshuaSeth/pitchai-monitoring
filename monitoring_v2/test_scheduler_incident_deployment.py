# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deployment contract for the scheduler placement observer."""

from __future__ import annotations

from pathlib import Path

from .testing_runtime import pytest


def test_scheduler_observer_deploys_without_telegram_credentials() -> None:
    """Keep the observer external to cells and behind the shared receiver policy."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(encoding="utf-8")
    start = workflow.index('echo "🚀 Starting scheduler placement incident observer..."')
    end = workflow.index('echo "🚀 Starting database dependency monitor..."')
    block = workflow[start:end]
    required_fragments = (
        "python -m monitoring_v2.scheduler_incident_observer",
        '--env-file "$SCHEDULER_OBSERVER_PROFILE"',
        "-v service-monitoring-state:/data",
        "--read-only",
    )
    missing = [fragment for fragment in required_fragments if fragment not in block]
    if missing:
        pytest.fail(f"scheduler observer deployment fragments are missing: {missing}")
    readiness_fragments = (
        'state["last_successful_directory_poll_at_ts"] > 0',
        'isinstance(state["cells"], dict)',
    )
    readiness_missing = [fragment for fragment in readiness_fragments if fragment not in workflow]
    if readiness_missing:
        pytest.fail(f"scheduler observer directory-readiness fragments are missing: {readiness_missing}")
    if "TELEGRAM_BOT_TOKEN" in block or "TELEGRAM_CHAT_ID" in block:
        pytest.fail("scheduler observer bypasses the shared receiver with direct Telegram credentials")
