#!/usr/bin/env python3
"""Example usage of the Production Log Collection Module.

This script demonstrates how to safely collect and analyze production
Docker container logs using the non-invasive log collection interface.

All operations are READ-ONLY and completely safe.
"""


from .log_interface import LogInterface
from .production_log_collector import ProductionLogCollector


def example_basic_usage():
    """Example of basic log collection usage."""
    print("🔍 Basic Production Log Collection Example")
    print("=" * 50)

    # Initialize the log interface
    interface = LogInterface()

    # Check system health first
    print("1. Checking system health...")
    if interface.check_health():
        print("   ✅ System is healthy and ready")
    else:
        print("   ❌ System health check failed")
        return

    # Get list of running containers
    print("\\n2. Getting running containers...")
    containers = interface.get_containers()
    print(f"   Found {len(containers)} running containers:")
    for container in containers:
        print(f"   📦 {container}")

    # Get recent logs from all containers
    print("\\n3. Collecting recent logs (last 1 hour)...")
    logs = interface.get_recent_logs(hours=1)
    total_entries = sum(len(container_logs) for container_logs in logs.values())
    print(f"   Collected {total_entries} log entries from {len(logs)} containers")

    # Get error logs only
    print("\\n4. Checking for recent errors...")
    errors = interface.get_recent_errors(hours=1)
    total_errors = sum(len(container_errors) for container_errors in errors.values())
    print(f"   Found {total_errors} error entries in {len(errors)} containers")

    # Get error summary
    print("\\n5. Generating error summary...")
    summary = interface.get_error_summary(hours=1)
    print(f"   Containers with errors: {summary['containers_with_errors']}")
    print(f"   Critical issues: {len(summary['critical_issues'])}")

    # Save logs to file
    print("\\n6. Saving logs to file...")
    filepath = interface.save_all_logs(hours=1)
    print(f"   ✅ Logs saved to: {filepath}")


def example_specific_container():
    """Example of getting logs from a specific container."""
    print("\\n🎯 Specific Container Log Collection Example")
    print("=" * 50)

    interface = LogInterface()

    # Get list of containers first
    containers = interface.get_containers()
    if not containers:
        print("   No containers found")
        return

    # Use the first container as an example
    container_name = containers[0]
    print(f"Getting logs from container: {container_name}")

    # Get logs from specific container
    logs = interface.get_logs(container_name, hours=2)
    print(f"   Retrieved {len(logs)} log entries")

    # Show recent log entries
    if logs:
        print("\\n   Recent log entries:")
        for log_entry in logs[-3:]:  # Last 3 entries
            timestamp = log_entry['timestamp'][:19]
            level = log_entry.get('level', 'INFO')
            message = log_entry['message'][:100]
            print(f"   [{timestamp}] {level}: {message}")


def example_error_analysis():
    """Example of detailed error analysis."""
    print("\\n🚨 Error Analysis Example")
    print("=" * 50)

    collector = ProductionLogCollector()

    # Get comprehensive error summary
    summary = collector.get_error_summary(hours=4)

    print("Analysis for last 4 hours:")
    print(f"   Total containers: {summary['total_containers']}")
    print(f"   Containers with errors: {summary['containers_with_errors']}")
    print(f"   Total error entries: {summary['total_error_entries']}")

    # Show critical issues
    if summary['critical_issues']:
        print(f"\\n   🔥 Critical Issues ({len(summary['critical_issues'])}):")
        for issue in summary['critical_issues']:
            print(f"     [{issue['container']}] {issue['message'][:80]}...")

    # Show error breakdown by container
    if summary['error_breakdown']:
        print("\\n   📋 Error Breakdown:")
        for container, details in summary['error_breakdown'].items():
            print(f"     {container}: {details['error_count']} errors")


def example_convenience_functions():
    """Example using convenience functions."""
    print("\\n⚡ Convenience Functions Example")
    print("=" * 50)

    # Import convenience functions
    from .log_interface import (
        get_production_errors,
        get_production_logs,
        save_production_logs,
    )

    # Quick log retrieval
    print("1. Quick log retrieval...")
    logs = get_production_logs(hours=1)
    total_entries = sum(len(container_logs) for container_logs in logs.values())
    print(f"   Retrieved {total_entries} entries from {len(logs)} containers")

    # Quick error retrieval
    print("\\n2. Quick error retrieval...")
    errors = get_production_errors(hours=1)
    total_errors = sum(len(container_errors) for container_errors in errors.values())
    print(f"   Found {total_errors} errors")

    # Quick save
    print("\\n3. Quick save to file...")
    filepath = save_production_logs(hours=1)
    print(f"   ✅ Saved to: {filepath}")


def main():
    """Run all examples."""
    print("🚀 Production Log Collection Module Examples")
    print("============================================")
    print("These examples demonstrate safe, read-only access to production logs")
    print()

    try:
        example_basic_usage()
        example_specific_container()
        example_error_analysis()
        example_convenience_functions()

        print("\\n✅ All examples completed successfully!")
        print("\\nThe production log collection module is ready for use.")
        print("All operations are safe and non-invasive.")

    except Exception as e:
        print(f"\\n❌ Example failed: {e}")
        print("\\nPlease check your environment variables:")
        print("- HETZNER_HOST")
        print("- HETZNER_USER")
        print("- HETZNER_SSH_KEY")


if __name__ == "__main__":
    main()
