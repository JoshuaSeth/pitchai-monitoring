from __future__ import annotations

from domain_checks.common_check import _is_browser_infra_error


class _DummyPlaywrightError(Exception):
    pass


def test_is_browser_infra_error_page_crashed() -> None:
    assert _is_browser_infra_error(_DummyPlaywrightError("Error: Page.goto: Page crashed")) is True


def test_is_browser_infra_error_target_crashed() -> None:
    assert _is_browser_infra_error(_DummyPlaywrightError("Error: Page.wait_for_selector: Target crashed")) is True
