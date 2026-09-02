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
        "-e PITCHAI_PLATFORM_CENTRAL_URL",
        "-e PITCHAI_PLATFORM_USER_TOKEN",
        "-v service-monitoring-state:/data",
        "--read-only",
        "--network host",
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


def test_scheduler_profile_uses_runtime_parser_before_container_teardown() -> None:
    """The installed profile and live central read must pass before teardown."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(encoding="utf-8")
    preflight = workflow.index('echo "🔎 Preflighting scheduler observer profile with the runtime parser..."')
    teardown = workflow.index('stop_rm_if_exists "$APP_NAME"')
    preflight_block = workflow[preflight:teardown]
    if "load_scheduler_incident_feed_config" not in preflight_block:
        pytest.fail("scheduler profile is not validated by the runtime parser before teardown")
    if "read_scheduler_cell_directory" not in preflight_block:
        pytest.fail("scheduler central connectivity is not proven before teardown")
    if "--network host" not in preflight_block:
        pytest.fail("scheduler loopback preflight cannot reach the host central service")
    if '. "$SCHEDULER_OBSERVER_PROFILE"' not in workflow[preflight:teardown]:
        pytest.fail("scheduler profile shell quoting is not normalized before runtime validation")
    if '--env-file "$SCHEDULER_OBSERVER_PROFILE"' in workflow:
        pytest.fail("scheduler profile values are still passed through a second env-file parser")
    if 'scheduler_central_url="$(grep' in workflow or 'scheduler_user_token="$(grep' in workflow:
        pytest.fail("scheduler profile validation still reparses Docker env-file syntax with grep")
