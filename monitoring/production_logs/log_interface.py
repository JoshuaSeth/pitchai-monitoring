"""Simple Log Interface for Production Log Access

This module provides a clean, easy-to-use interface for accessing production
Docker container logs. All operations are safe and read-only.

Example Usage:
    from monitoring.production_logs import LogInterface

    # Simple usage
    interface = LogInterface()
    logs = interface.get_recent_logs()  # Last hour from all containers
    errors = interface.get_recent_errors()  # Error logs only

    # Specific container
    app_logs = interface.get_logs("web-app", hours=2)

    # Save logs to file
    file_path = interface.save_all_logs(hours=4)
"""

from typing import Any

import structlog

from .production_log_collector import ProductionLogCollector

logger = structlog.get_logger(__name__)


class LogInterface:
    """Simple interface for production log access.

    Provides convenient methods for common log operations while maintaining
    the same safety guarantees as the underlying ProductionLogCollector.
    """

    def __init__(self):
        """Initialize the log interface."""
        self.collector = ProductionLogCollector()
        logger.info("Log interface initialized")

    def get_containers(self) -> list[str]:
        """Get list of running container names.

        Returns:
            List of container names
        """
        containers = self.collector.get_container_list()
        return [container['name'] for container in containers]

    def get_recent_logs(self, hours: int = 1) -> dict[str, list[dict[str, Any]]]:
        """Get recent logs from all containers.

        Args:
            hours: Number of hours back to retrieve (default: 1)

        Returns:
            Dictionary mapping container names to log entries
        """
        return self.collector.get_logs_from_all_containers(hours)

    def get_recent_errors(self, hours: int = 1) -> dict[str, list[dict[str, Any]]]:
        """Get recent error logs from all containers.

        Args:
            hours: Number of hours back to analyze (default: 1)

        Returns:
            Dictionary mapping container names to error log entries
        """
        return self.collector.get_error_logs_only(hours)

    def get_logs(self, container_name: str, hours: int = 1) -> list[dict[str, Any]]:
        """Get logs from a specific container.

        Args:
            container_name: Name of the container
            hours: Number of hours back to retrieve (default: 1)

        Returns:
            List of log entries
        """
        return self.collector.get_logs_from_container(container_name, hours)

    def get_error_summary(self, hours: int = 1) -> dict[str, Any]:
        """Get summary of errors across all containers.

        Args:
            hours: Number of hours back to analyze (default: 1)

        Returns:
            Structured error summary
        """
        return self.collector.get_error_summary(hours)

    def save_all_logs(self, hours: int = 1, filename: str | None = None) -> str:
        """Collect and save logs from all containers to a file.

        Args:
            hours: Number of hours back to collect (default: 1)
            filename: Optional filename (auto-generated if not provided)

        Returns:
            Path to the saved log file
        """
        logs = self.get_recent_logs(hours)
        return self.collector.save_logs_to_file(logs, filename)

    def check_health(self) -> bool:
        """Check if the log collection system is healthy.

        Returns:
            True if system is healthy, False otherwise
        """
        health = self.collector.health_check()
        return health['status'] == 'healthy'

    def print_container_status(self) -> None:
        """Print a summary of running containers (for CLI usage)."""
        try:
            containers = self.collector.get_container_list()

            print(f"\\n🔍 Production Server Status ({len(containers)} containers)")
            print("=" * 50)

            for container in containers:
                print(f"📦 {container['name']}")
                print(f"   Image: {container['image']}")
                print(f"   Status: {container['status']}")
                if container['ports']:
                    print(f"   Ports: {container['ports']}")
                print()

        except Exception as e:
            print(f"❌ Failed to get container status: {e}")

    def print_recent_errors(self, hours: int = 1) -> None:
        """Print recent errors in a human-readable format (for CLI usage).

        Args:
            hours: Number of hours back to check (default: 1)
        """
        try:
            error_summary = self.get_error_summary(hours)

            print(f"\\n🚨 Error Summary (Last {hours} hour{'s' if hours > 1 else ''})")
            print("=" * 50)
            print(f"Containers checked: {error_summary['total_containers']}")
            print(f"Containers with errors: {error_summary['containers_with_errors']}")
            print(f"Total error entries: {error_summary['total_error_entries']}")

            if error_summary['critical_issues']:
                print(f"\\n🔥 Critical Issues ({len(error_summary['critical_issues'])})")
                for issue in error_summary['critical_issues']:
                    print(f"   [{issue['container']}] {issue['message'][:100]}...")

            if error_summary['error_breakdown']:
                print("\\n📋 Error Breakdown")
                for container, details in error_summary['error_breakdown'].items():
                    print(f"   {container}: {details['error_count']} errors")
                    if details['recent_errors']:
                        latest = details['recent_errors'][-1]
                        print(f"      Latest: {latest['message'][:80]}...")

            if error_summary['total_error_entries'] == 0:
                print("✅ No errors found in the specified time period")

        except Exception as e:
            print(f"❌ Failed to get error summary: {e}")


# Convenience functions for quick access
def get_production_logs(hours: int = 1) -> dict[str, list[dict[str, Any]]]:
    """Quick function to get production logs.

    Args:
        hours: Number of hours back to retrieve

    Returns:
        Dictionary mapping container names to log entries
    """
    interface = LogInterface()
    return interface.get_recent_logs(hours)


def get_production_errors(hours: int = 1) -> dict[str, list[dict[str, Any]]]:
    """Quick function to get production error logs.

    Args:
        hours: Number of hours back to analyze

    Returns:
        Dictionary mapping container names to error log entries
    """
    interface = LogInterface()
    return interface.get_recent_errors(hours)


def save_production_logs(hours: int = 1, filename: str | None = None) -> str:
    """Quick function to save production logs to file.

    Args:
        hours: Number of hours back to collect
        filename: Optional filename

    Returns:
        Path to saved file
    """
    interface = LogInterface()
    return interface.save_all_logs(hours, filename)
