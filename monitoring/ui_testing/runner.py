"""UI test runner using Playwright for production environments."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..config import get_config

logger = structlog.get_logger(__name__)


class TestResult:
    """Represents the result of a UI test execution."""

    def __init__(
        self,
        test_name: str,
        success: bool,
        duration: float,
        error: str | None = None,
        screenshot_path: str | None = None,
        metadata: dict[str, Any] | None = None
    ):
        self.test_name = test_name
        self.success = success
        self.duration = duration
        self.error = error
        self.screenshot_path = screenshot_path
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert test result to dictionary."""
        return {
            "test_name": self.test_name,
            "success": self.success,
            "duration": self.duration,
            "error": self.error,
            "screenshot_path": self.screenshot_path,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }


class UITestRunner:
    """Runs UI tests against production environments using Playwright."""

    def __init__(self):
        self.config = get_config()
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()

    async def start(self):
        """Initialize the browser and context."""
        logger.info("Starting UI test runner")

        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.config.browser_headless
        )
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    async def stop(self):
        """Cleanup browser resources."""
        logger.info("Stopping UI test runner")

        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()

    async def run_test(self, test_config: dict[str, Any]) -> TestResult:
        """Run a single UI test based on configuration."""
        test_name = test_config.get("flow_name", "unknown_test")
        start_time = time.time()

        logger.info("Running UI test", test_name=test_name)

        page = await self.context.new_page()
        screenshot_path = None

        try:
            # Execute test steps
            await self._execute_test_steps(page, test_config)

            duration = time.time() - start_time
            logger.info("UI test passed", test_name=test_name, duration=duration)

            return TestResult(
                test_name=test_name,
                success=True,
                duration=duration,
                metadata=test_config.get("metadata", {})
            )

        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)

            # Take screenshot on failure if enabled
            if self.config.screenshot_on_failure:
                screenshot_path = await self._take_screenshot(page, test_name)

            logger.error("UI test failed", test_name=test_name, error=error_msg, duration=duration)

            return TestResult(
                test_name=test_name,
                success=False,
                duration=duration,
                error=error_msg,
                screenshot_path=screenshot_path,
                metadata=test_config.get("metadata", {})
            )

        finally:
            await page.close()

    async def _execute_test_steps(self, page: Page, test_config: dict[str, Any]):
        """Execute the individual steps of a UI test."""
        steps = test_config.get("steps", [])
        target_url = test_config.get("target_url")

        if target_url:
            await page.goto(target_url, timeout=self.config.ui_test_timeout * 1000)

        for step in steps:
            await self._execute_step(page, step)

    async def _execute_step(self, page: Page, step: dict[str, Any]):
        """Execute a single test step."""
        action = step.get("action")
        selector = step.get("selector")
        value = step.get("value")

        logger.debug("Executing test step", action=action, selector=selector)

        if action == "click":
            await page.click(selector, timeout=self.config.ui_test_timeout * 1000)
        elif action == "fill":
            await page.fill(selector, value, timeout=self.config.ui_test_timeout * 1000)
        elif action == "wait_for":
            await page.wait_for_selector(selector, timeout=self.config.ui_test_timeout * 1000)
        elif action == "assert_visible":
            element = await page.query_selector(selector)
            if not element or not await element.is_visible():
                raise AssertionError(f"Element {selector} is not visible")
        elif action == "assert_text":
            element = await page.query_selector(selector)
            if not element:
                raise AssertionError(f"Element {selector} not found")
            text = await element.text_content()
            if value not in text:
                raise AssertionError(f"Expected text '{value}' not found in '{text}'")
        elif action == "navigate":
            await page.goto(value, timeout=self.config.ui_test_timeout * 1000)
        elif action == "wait":
            await asyncio.sleep(float(value))
        else:
            raise ValueError(f"Unknown action: {action}")

    async def _take_screenshot(self, page: Page, test_name: str) -> str:
        """Take a screenshot and return the file path."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{test_name}_{timestamp}.png"
        screenshot_path = Path(self.config.reports_directory) / "screenshots" / filename
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        await page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path)

    async def run_test_suite(self, test_configs: list[dict[str, Any]]) -> list[TestResult]:
        """Run multiple UI tests and return results."""
        results = []

        logger.info("Running UI test suite", test_count=len(test_configs))

        for test_config in test_configs:
            result = await self.run_test(test_config)
            results.append(result)

        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed

        logger.info("UI test suite completed", total=len(results), passed=passed, failed=failed)

        return results
