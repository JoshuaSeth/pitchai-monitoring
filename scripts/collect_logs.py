#!/usr/bin/env python3
"""Standalone script to collect Docker logs."""

import argparse
import sys
from pathlib import Path

# Add parent directory to path to import monitoring modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

from monitoring.config import get_config
from monitoring.log_collector.docker_logs import DockerLogCollector
from monitoring.log_collector.log_processor import LogProcessor

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


def main():
    """Collect Docker logs and generate analysis."""
    parser = argparse.ArgumentParser(description="Collect Docker container logs")
    parser.add_argument("--hours", type=int, default=1, help="Hours of logs to collect (default: 1)")
    parser.add_argument("--containers", nargs="*", help="Specific containers to collect from")
    parser.add_argument("--errors-only", action="store_true", help="Show only error logs")

    args = parser.parse_args()

    get_config()

    logger.info("Starting log collection", hours=args.hours)

    # Collect logs
    with DockerLogCollector() as collector:
        container_logs = collector.collect_logs_for_timeframe(
            containers=args.containers,
            hours_back=args.hours
        )

    # Process logs
    processor = LogProcessor()

    # Save logs to file
    log_file = processor.save_logs_to_file(container_logs)

    # Generate summary
    log_summary = processor.generate_log_summary(container_logs)

    # Print summary
    print("\n" + "="*50)
    print("LOG COLLECTION SUMMARY")
    print("="*50)
    print(f"Time Range: {args.hours} hour(s)")
    print(f"Containers: {len(container_logs)}")
    print(f"Total Logs: {log_summary['total_logs']}")
    print(f"Total Errors: {log_summary['total_errors']}")
    print(f"Total Warnings: {log_summary['total_warnings']}")

    print("\nPer Container:")
    for container, summary in log_summary["containers"].items():
        print(f"  {container}:")
        print(f"    Logs: {summary['log_count']}")
        print(f"    Errors: {summary['error_count']}")
        print(f"    Warnings: {summary['warning_count']}")

    if args.errors_only and log_summary['total_errors'] > 0:
        print("\nERROR LOGS:")
        for container, logs in container_logs.items():
            error_analysis = processor.analyze_error_patterns(logs)
            for error in error_analysis["errors"]:
                print(f"[{error['timestamp']}] {error['container']}: {error['message']}")

    print(f"\nLogs saved to: {log_file}")

    return log_summary['total_errors'] == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
