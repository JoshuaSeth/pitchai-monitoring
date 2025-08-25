#!/usr/bin/env python3
"""Generate a daily monitoring report for team leads."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
import json

# Add parent directory to path to import monitoring modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitoring.reporting.report_generator import ReportGenerator
from monitoring.reporting.incident_tracker import IncidentTracker
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


def load_recent_test_results(reports_dir: Path, days_back: int = 1) -> list:
    """Load test results from recent report files."""
    test_results = []
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)
    
    for report_file in reports_dir.glob("test_results_*.json"):
        try:
            # Extract date from filename
            date_str = report_file.stem.split("_")[-2:]  # ['20250816', '143522']
            if len(date_str) == 2:
                file_date = datetime.strptime(f"{date_str[0]}_{date_str[1]}", "%Y%m%d_%H%M%S")
                
                if file_date >= cutoff_date:
                    with open(report_file, 'r') as f:
                        report_data = json.load(f)
                        test_results.extend(report_data.get("test_results", []))
        except Exception as e:
            logger.warning("Failed to load report file", file=report_file.name, error=str(e))
    
    return test_results


def load_recent_log_summary(logs_dir: Path, days_back: int = 1):
    """Load the most recent log summary."""
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)
    latest_summary = None
    latest_date = None
    
    for log_file in logs_dir.glob("logs_*.json"):
        try:
            # Extract date from filename
            date_str = log_file.stem.split("_")[-2:]  # ['20250816', '143522']
            if len(date_str) == 2:
                file_date = datetime.strptime(f"{date_str[0]}_{date_str[1]}", "%Y%m%d_%H%M%S")
                
                if file_date >= cutoff_date and (latest_date is None or file_date > latest_date):
                    with open(log_file, 'r') as f:
                        # This is raw log data, we'd need to process it
                        # For now, just return basic info
                        log_data = json.load(f)
                        total_logs = sum(len(logs) for logs in log_data.values())
                        latest_summary = {
                            "total_logs": total_logs,
                            "total_errors": 0,  # Would need to analyze
                            "total_warnings": 0  # Would need to analyze
                        }
                        latest_date = file_date
        except Exception as e:
            logger.warning("Failed to load log file", file=log_file.name, error=str(e))
    
    return latest_summary


def main():
    """Generate daily report for team leads."""
    config = get_config()
    
    logger.info("Generating daily monitoring report")
    
    # Setup paths
    reports_dir = Path(config.reports_directory)
    logs_dir = Path(config.logs_directory)
    
    # Load recent data
    test_results_data = load_recent_test_results(reports_dir)
    log_summary = load_recent_log_summary(logs_dir)
    
    # Convert test result dicts back to objects for report generation
    from monitoring.ui_testing.runner import TestResult
    test_results = []
    for result_dict in test_results_data:
        test_result = TestResult(
            test_name=result_dict["test_name"],
            success=result_dict["success"],
            duration=result_dict["duration"],
            error=result_dict.get("error"),
            screenshot_path=result_dict.get("screenshot_path"),
            metadata=result_dict.get("metadata", {})
        )
        test_result.timestamp = result_dict["timestamp"]
        test_results.append(test_result)
    
    # Generate report
    report_generator = ReportGenerator()
    daily_summary = report_generator.generate_daily_summary(test_results, log_summary)
    
    # Get incident statistics
    incident_tracker = IncidentTracker()
    incident_stats = incident_tracker.get_incident_statistics(days_back=1)
    
    # Print team lead summary
    print("\n" + "="*60)
    print("DAILY MONITORING REPORT")
    print("="*60)
    print(f"Date: {daily_summary['date']}")
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    
    overview = daily_summary["overview"]
    print(f"\nOVERVIEW:")
    print(f"  Total Test Runs: {overview['total_test_runs']}")
    print(f"  Unique Tests: {overview['unique_tests']}")
    print(f"  Overall Success Rate: {overview['overall_success_rate']:.1f}%")
    print(f"  Total Issues: {overview['total_issues']}")
    
    print(f"\nINCIDENTS (Last 24h):")
    print(f"  Total Incidents: {incident_stats['total_incidents']}")
    print(f"  Open Incidents: {incident_stats['resolution_statistics']['open_incidents']}")
    print(f"  Resolved: {incident_stats['resolution_statistics']['resolved_incidents']}")
    
    if incident_stats.get('most_problematic_test'):
        print(f"  Most Issues: {incident_stats['most_problematic_test']}")
    
    # Show issues
    issues = daily_summary.get("issues", [])
    if issues:
        print(f"\nISSUES REQUIRING ATTENTION:")
        for issue in issues:
            severity = issue.get("severity", "medium").upper()
            print(f"  [{severity}] {issue.get('type', 'unknown')}")
            if 'test_name' in issue:
                print(f"    Test: {issue['test_name']}")
            if 'success_rate' in issue:
                print(f"    Success Rate: {issue['success_rate']:.1f}%")
            if 'error_count' in issue:
                print(f"    Error Count: {issue['error_count']}")
    
    # Show recommendations
    recommendations = daily_summary.get("recommendations", [])
    if recommendations:
        print(f"\nRECOMMENDATIONS:")
        for rec in recommendations:
            priority = rec.get("priority", "medium").upper()
            print(f"  [{priority}] {rec.get('message', 'No message')}")
    
    # Show test statistics
    test_stats = daily_summary.get("test_statistics", {})
    if test_stats:
        print(f"\nTEST PERFORMANCE:")
        for test_name, stats in test_stats.items():
            if stats["success_rate"] < 90:  # Only show problematic tests
                print(f"  {test_name}:")
                print(f"    Success Rate: {stats['success_rate']:.1f}%")
                print(f"    Runs: {stats['total_runs']}")
                print(f"    Avg Duration: {stats['avg_duration']:.1f}s")
    
    print(f"\nReport saved to: daily_summary_{daily_summary['date']}.json")
    print("\nFor detailed information, check the reports/ and incidents/ directories.")
    
    # Return True if no critical issues
    critical_issues = [i for i in issues if i.get("severity") == "high"]
    return len(critical_issues) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)