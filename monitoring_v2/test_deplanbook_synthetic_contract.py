# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for the shared DePlanBook synthetic contract."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import cast

_CHECK_ROOT = Path(__file__).parents[1] / "domain_checks"
_CONFIG_ERROR = "DePlanBook plugin did not define a CHECK mapping"
_CONTRACT_ERROR = "DePlanBook diary synthetic no longer enforces the anonymous login boundary"
_EXPECTED_SYNTHETIC: list[dict[str, object]] = [
    {
        "name": "open_diary_page",
        "steps": [
            {"type": "goto"},
            {"type": "click", "selector": 'a[href="/diary"]'},
            {"type": "expect_url_contains", "value": "/login-page?next=%2Fdiary"},
            {"type": "wait_for_selector", "selector": "text=Log in bij DePlanBook", "state": "visible"},
        ],
    },
]


def test_diary_synthetic_verifies_anonymous_login_boundary() -> None:
    """Require canonical and alias checks to share the protected-route proof.

    Raises:
        AssertionError: A plugin no longer proves the login boundary.
        TypeError: A plugin does not expose its domain-check mapping.
    """
    for domain in ("deplanbook.com", "dpb.pitchai.net"):
        plugin_path = _CHECK_ROOT / domain / "check.py"
        module_variables = cast("dict[str, object]", runpy.run_path(str(plugin_path)))
        check = module_variables.get("CHECK")
        if not isinstance(check, dict):
            raise TypeError(_CONFIG_ERROR)
        typed_check = cast("dict[str, object]", check)
        if typed_check.get("synthetic_transactions") != _EXPECTED_SYNTHETIC:
            raise AssertionError(_CONTRACT_ERROR)
