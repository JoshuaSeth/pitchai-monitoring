# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser infrastructure-error classification tests."""

from __future__ import annotations

from domain_checks.common_check import chromium_launch_arguments, is_browser_infrastructure_error
from domain_checks.testing import verify

_EXPECTED_BASE_ARGUMENTS = [
    "--no-sandbox", "--disable-gpu", "--disable-extensions",
    "--disable-background-networking", "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
    "--disable-sync", "--metrics-recording-only", "--no-first-run",
    "--no-default-browser-check", "--disable-features=site-per-process",
]


class _DummyPlaywrightError(Exception):
    pass


def test_chromium_launch_policy_preserves_both_runtime_profiles() -> None:
    """Lock the monitor and E2E launch flags while sharing one policy source."""
    monitor_arguments = chromium_launch_arguments(disable_dev_shm=False)
    e2e_arguments = chromium_launch_arguments(disable_dev_shm=True)

    verify(monitor_arguments == _EXPECTED_BASE_ARGUMENTS)
    expected_e2e = _EXPECTED_BASE_ARGUMENTS.copy()
    expected_e2e.insert(1, "--disable-dev-shm-usage")
    verify(e2e_arguments == expected_e2e)

    monitor_arguments.append("--probe-mutation")
    verify(chromium_launch_arguments(disable_dev_shm=False) == _EXPECTED_BASE_ARGUMENTS)


def test_is_browser_infra_error_page_crashed() -> None:
    """Verify page crashes classify as browser infrastructure failures."""
    error = _DummyPlaywrightError("Error: Page.goto: Page crashed")
    verify(is_browser_infrastructure_error(error) is True)


def test_is_browser_infra_error_target_crashed() -> None:
    """Verify target crashes classify as browser infrastructure failures."""
    error = _DummyPlaywrightError("Error: Page.wait_for_selector: Target crashed")
    verify(is_browser_infrastructure_error(error) is True)


def test_is_browser_infra_error_driver_connection_closed() -> None:
    """Verify driver disconnects classify as browser infrastructure failures."""
    error = _DummyPlaywrightError(
        "Exception: Browser.new_context: Connection closed while reading from the driver",
    )
    verify(is_browser_infrastructure_error(error) is True)
