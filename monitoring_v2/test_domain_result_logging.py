# Copyright (c) 2026 PitchAI. All rights reserved.
"""Quiet inventory failures retain diagnostics, not warning-level noise."""

from __future__ import annotations

import logging

from .inventory import CONFIG_PATH, EXPECTED_DASHBOARD_ONLY_DOMAINS, production_domains
from .result_logging import DomainResultLogFilter, install_result_log_policy
from .testing_runtime import pytest


def test_all_inventory_results_respect_alert_policy_severity() -> None:
    """Cover both live result templates, all targets and unrelated warnings."""
    policy_filter = DomainResultLogFilter(EXPECTED_DASHBOARD_ONLY_DOMAINS)
    templates = ("Domain result domain=%s ok=False", "Domain failing (alert suppressed) domain=%s fail_streak=1/2")
    for entry in production_domains():
        domain = entry["domain"]
        for template in templates:
            record = logging.LogRecord("service-monitoring", logging.WARNING, __file__, 1, template, (domain,), None)
            retained = policy_filter.filter(record)
            expected = logging.INFO if domain in EXPECTED_DASHBOARD_ONLY_DOMAINS else logging.WARNING
            if not retained or record.levelno != expected:
                pytest.fail(f"result log policy drifted: {domain}")
    for level, template in ((logging.ERROR, templates[0]), (logging.WARNING, "Collector failed domain=%s")):
        record = logging.LogRecord("service-monitoring", level, __file__, 1, template, ("registry.pitchai.net",), None)
        if not policy_filter.filter(record) or record.levelno != level:
            pytest.fail("quiet policy suppressed an unrelated warning or error")


def test_launcher_installs_exact_selected_inventory_policy() -> None:
    """Require the production launcher and exact inventory-derived quiet set."""
    logger = logging.getLogger("service-monitoring")
    installed = install_result_log_policy(CONFIG_PATH)
    try:
        if installed.quiet_domains != EXPECTED_DASHBOARD_ONLY_DOMAINS:
            pytest.fail("logging policy differs from canonical quiet inventory")
        launcher = CONFIG_PATH.parents[1] / "ops" / "run-service-monitoring.sh"
        if "python -m monitoring_v2.monitor_launcher" not in launcher.read_text(encoding="utf-8"):
            pytest.fail("production watchdog does not install result logging policy")
    finally:
        logger.removeFilter(installed)
