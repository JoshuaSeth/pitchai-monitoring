# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep the deployed hotpath inventory bound to the checked-in inventory."""

from __future__ import annotations

import json
from pathlib import Path

from .testing_runtime import pytest

_REPO_ROOT = Path(__file__).parents[1]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci-cd.yaml"
_INVENTORY_PATH = _REPO_ROOT / "e2e_registry" / "hotpath_inventory.json"
_RETIRED_LANE_ID = "quickchat-rsr-hotpath-monitor"
_OVERRIDE_REMOVAL = "sed -i '/^E2E_HOTPATH_INVENTORY_PATH=/d'"
_RUNTIME_ASSERTION = "runtime hotpath inventory diverges from the checked-in inventory"


def test_deploy_removes_any_runtime_inventory_override() -> None:
    """A divergent mounted inventory must not survive a deployment."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    if _OVERRIDE_REMOVAL not in workflow:
        pytest.fail("deployment no longer removes the runtime hotpath inventory override")


def test_deploy_asserts_runtime_inventory_matches_checked_in_inventory() -> None:
    """Deployment must fail closed when the served lane set diverges."""
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    if _RUNTIME_ASSERTION not in workflow:
        pytest.fail("deployment no longer asserts the served hotpath inventory")


def test_checked_in_inventory_keeps_the_retired_lane_out() -> None:
    """The retired RSR lane stays retired until its demo surface returns."""
    inventory = json.loads(_INVENTORY_PATH.read_text(encoding="utf-8"))
    lane_ids = [lane["lane_id"] for lane in inventory["lanes"]]

    if _RETIRED_LANE_ID in lane_ids:
        pytest.fail("retired QuickChat RSR lane was re-admitted without a deployed demo surface")
