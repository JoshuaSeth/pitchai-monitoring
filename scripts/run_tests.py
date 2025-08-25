#!/usr/bin/env python3
"""Standalone script to run UI tests."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import monitoring modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.ui_testing.runner import UITestRunner
from monitoring.ui_testing.test_manager import TestManager
from monitoring.reporting.report_generator import ReportGenerator
from monitoring.config import get_config
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


async def main():
    """Run UI tests and generate report."""
    config = get_config()
    
    logger.info("Starting UI test execution")
    
    # Load tests
    test_manager = TestManager()
    test_configs = test_manager.load_all_tests()
    
    if not test_configs:
        logger.warning("No test configurations found")
        return
    
    # Filter for production environment
    filtered_tests = test_manager.filter_tests_by_environment(test_configs, config.environment)
    
    logger.info("Running tests", count=len(filtered_tests))
    
    # Run tests
    async with UITestRunner() as runner:
        test_results = await runner.run_test_suite(filtered_tests)
    
    # Generate report
    report_generator = ReportGenerator()
    report_data = report_generator.generate_test_results_report(test_results)
    
    # Print summary
    summary = report_data["summary"]
    print("\n" + "="*50)
    print("UI TEST RESULTS SUMMARY")
    print("="*50)
    print(f"Total Tests: {summary['total_tests']}")
    print(f"Passed: {summary['passed']}")
    print(f"Failed: {summary['failed']}")
    print(f"Success Rate: {summary['success_rate']:.1f}%")
    print(f"Total Duration: {summary['total_duration']:.2f}s")
    print(f"Average Duration: {summary['average_duration']:.2f}s")
    
    if summary['failed'] > 0:
        print("\nFAILED TESTS:")
        for result in test_results:
            if not result.success:
                print(f"- {result.test_name}: {result.error}")
    
    print(f"\nReport saved: {report_data.get('report_name', 'Unknown')}.json")
    
    return summary['failed'] == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)