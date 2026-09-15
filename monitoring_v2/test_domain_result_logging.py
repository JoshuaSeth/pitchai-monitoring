# Copyright (c) 2026 PitchAI. All rights reserved.
"""Quiet inventory failures remain observable without warning-level noise."""

from __future__ import annotations

import logging

from domain_checks.result_logging import domain_result_log_level

from .domain_runtime import inventory_runtime
from .inventory import production_domains
from .testing_runtime import pytest


def test_all_inventory_results_respect_alert_policy_severity() -> None:
    """Cover healthy results and failures for every configured alert mode."""
    for entry in production_domains():
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        healthy = domain_result_log_level(ok=True, alertable=policy.telegram_enabled)
        failed = domain_result_log_level(ok=False, alertable=policy.telegram_enabled)
        expected_failure = logging.WARNING if policy.telegram_enabled else logging.INFO
        if healthy != logging.INFO or failed != expected_failure:
            pytest.fail(f"result log severity disagrees with inventory: {entry['domain']}")
