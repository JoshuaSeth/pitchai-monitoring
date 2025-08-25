"""Report generation for test results and monitoring data."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader

from ..config import get_config
from ..log_collector.docker_logs import LogEntry
from ..ui_testing.runner import TestResult

logger = structlog.get_logger(__name__)


class ReportGenerator:
    """Generates structured reports for monitoring results."""

    def __init__(self):
        self.config = get_config()
        self.reports_dir = Path(self.config.reports_directory)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Setup Jinja2 for HTML reports
        template_dir = Path(__file__).parent / "templates"
        if template_dir.exists():
            self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
        else:
            self.jinja_env = None

    def generate_test_results_report(
        self,
        test_results: list[TestResult],
        report_name: str | None = None
    ) -> dict[str, Any]:
        """Generate a comprehensive test results report."""
        if report_name is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            report_name = f"test_results_{timestamp}"

        # Calculate summary statistics
        total_tests = len(test_results)
        passed_tests = sum(1 for result in test_results if result.success)
        failed_tests = total_tests - passed_tests

        # Calculate durations
        total_duration = sum(result.duration for result in test_results)
        avg_duration = total_duration / total_tests if total_tests > 0 else 0

        # Group failures by error type
        failure_groups = {}
        for result in test_results:
            if not result.success and result.error:
                error_type = self._categorize_error(result.error)
                if error_type not in failure_groups:
                    failure_groups[error_type] = []
                failure_groups[error_type].append(result)

        report_data = {
            "report_name": report_name,
            "generation_timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_tests": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
                "total_duration": total_duration,
                "average_duration": avg_duration
            },
            "test_results": [result.to_dict() for result in test_results],
            "failure_analysis": {
                "failure_groups": {
                    group: [result.to_dict() for result in results]
                    for group, results in failure_groups.items()
                },
                "most_common_error": max(failure_groups.keys(), key=lambda k: len(failure_groups[k])) if failure_groups else None
            },
            "recommendations": self._generate_test_recommendations(test_results, failure_groups)
        }

        # Save JSON report
        json_path = self.reports_dir / f"{report_name}.json"
        with open(json_path, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)

        logger.info("Generated test results report",
                   report=report_name,
                   total_tests=total_tests,
                   success_rate=report_data["summary"]["success_rate"])

        return report_data

    def generate_incident_report(
        self,
        test_result: TestResult,
        log_correlation: dict[str, Any] | None = None,
        incident_id: str | None = None
    ) -> dict[str, Any]:
        """Generate an incident report for a failed test."""
        if incident_id is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            incident_id = f"incident_{test_result.test_name}_{timestamp}".replace(" ", "_")

        incident_data = {
            "incident_id": incident_id,
            "test_name": test_result.test_name,
            "failure_time": test_result.timestamp,
            "creation_time": datetime.utcnow().isoformat(),
            "reproducible": None,  # To be filled by ops engineer
            "test_details": test_result.to_dict(),
            "error_analysis": {
                "error_message": test_result.error,
                "error_category": self._categorize_error(test_result.error) if test_result.error else None,
                "screenshot_available": test_result.screenshot_path is not None
            },
            "log_correlation": log_correlation,
            "investigation": {
                "ops_contact": None,
                "root_cause": None,
                "resolution": None,
                "test_update_needed": None,
                "status": "open"
            },
            "metadata": test_result.metadata
        }

        # Save incident report
        incident_path = Path(self.config.incidents_directory) / f"{incident_id}.json"
        incident_path.parent.mkdir(parents=True, exist_ok=True)

        with open(incident_path, 'w') as f:
            json.dump(incident_data, f, indent=2, default=str)

        logger.info("Generated incident report",
                   incident_id=incident_id,
                   test_name=test_result.test_name)

        return incident_data

    def generate_daily_summary(
        self,
        test_results: list[TestResult],
        log_summary: dict[str, Any] | None = None,
        date: datetime | None = None
    ) -> dict[str, Any]:
        """Generate a daily summary report for team leads."""
        if date is None:
            date = datetime.utcnow()

        date_str = date.strftime("%Y-%m-%d")

        # Group results by test
        test_groups = {}
        for result in test_results:
            if result.test_name not in test_groups:
                test_groups[result.test_name] = []
            test_groups[result.test_name].append(result)

        # Calculate per-test statistics
        test_statistics = {}
        for test_name, results in test_groups.items():
            total_runs = len(results)
            successes = sum(1 for r in results if r.success)

            test_statistics[test_name] = {
                "total_runs": total_runs,
                "successes": successes,
                "failures": total_runs - successes,
                "success_rate": (successes / total_runs * 100) if total_runs > 0 else 0,
                "last_run": max(results, key=lambda r: r.timestamp).to_dict(),
                "avg_duration": sum(r.duration for r in results) / total_runs if total_runs > 0 else 0
            }

        # Identify issues
        issues = []
        for test_name, stats in test_statistics.items():
            if stats["success_rate"] < 90:
                issues.append({
                    "type": "low_success_rate",
                    "test_name": test_name,
                    "success_rate": stats["success_rate"],
                    "severity": "high" if stats["success_rate"] < 50 else "medium"
                })

        # Add log issues if available
        if log_summary:
            if log_summary.get("total_errors", 0) > 10:
                issues.append({
                    "type": "high_error_volume",
                    "error_count": log_summary["total_errors"],
                    "severity": "high"
                })

        summary_data = {
            "date": date_str,
            "generation_timestamp": datetime.utcnow().isoformat(),
            "overview": {
                "total_test_runs": len(test_results),
                "unique_tests": len(test_groups),
                "overall_success_rate": (sum(1 for r in test_results if r.success) / len(test_results) * 100) if test_results else 0,
                "total_issues": len(issues)
            },
            "test_statistics": test_statistics,
            "issues": issues,
            "log_summary": log_summary,
            "recommendations": self._generate_daily_recommendations(test_statistics, issues, log_summary)
        }

        # Save summary
        summary_path = self.reports_dir / f"daily_summary_{date_str}.json"
        with open(summary_path, 'w') as f:
            json.dump(summary_data, f, indent=2, default=str)

        logger.info("Generated daily summary",
                   date=date_str,
                   total_runs=len(test_results),
                   issues=len(issues))

        return summary_data

    def _categorize_error(self, error_message: str) -> str:
        """Categorize error messages into types."""
        error_lower = error_message.lower()

        if "timeout" in error_lower:
            return "timeout"
        elif "connection" in error_lower:
            return "connection"
        elif "element" in error_lower and ("not found" in error_lower or "not visible" in error_lower):
            return "element_not_found"
        elif "assertion" in error_lower:
            return "assertion_failure"
        elif "500" in error_lower or "internal server error" in error_lower:
            return "server_error"
        elif "404" in error_lower or "not found" in error_lower:
            return "not_found"
        else:
            return "unknown"

    def _generate_test_recommendations(
        self,
        test_results: list[TestResult],
        failure_groups: dict[str, list[TestResult]]
    ) -> list[dict[str, str]]:
        """Generate recommendations based on test results."""
        recommendations = []

        if not test_results:
            return recommendations

        # High failure rate
        failed_count = sum(1 for r in test_results if not r.success)
        failure_rate = failed_count / len(test_results)

        if failure_rate > 0.5:
            recommendations.append({
                "type": "high_failure_rate",
                "message": f"High failure rate ({failure_rate:.1%}). Consider reviewing test environments and infrastructure.",
                "priority": "high"
            })

        # Timeout issues
        if "timeout" in failure_groups:
            recommendations.append({
                "type": "timeout_issues",
                "message": f"{len(failure_groups['timeout'])} tests failed due to timeouts. Consider increasing timeout values or investigating performance issues.",
                "priority": "medium"
            })

        # Element not found issues
        if "element_not_found" in failure_groups:
            recommendations.append({
                "type": "ui_changes",
                "message": f"{len(failure_groups['element_not_found'])} tests failed due to missing elements. UI may have changed - review and update tests.",
                "priority": "high"
            })

        return recommendations

    def _generate_daily_recommendations(
        self,
        test_statistics: dict[str, Any],
        issues: list[dict[str, Any]],
        log_summary: dict[str, Any] | None
    ) -> list[dict[str, str]]:
        """Generate daily recommendations for the team lead."""
        recommendations = []

        # Check for failing tests
        failing_tests = [name for name, stats in test_statistics.items() if stats["success_rate"] < 90]
        if failing_tests:
            recommendations.append({
                "type": "failing_tests",
                "message": f"Tests with low success rates: {', '.join(failing_tests)}. Investigate and fix or update tests.",
                "priority": "high"
            })

        # Check for high error volume in logs
        if log_summary and log_summary.get("total_errors", 0) > 20:
            recommendations.append({
                "type": "high_error_volume",
                "message": f"High error volume in logs ({log_summary['total_errors']} errors). Review application health.",
                "priority": "medium"
            })

        # No major issues
        if not issues:
            recommendations.append({
                "type": "all_good",
                "message": "All monitoring systems running smoothly. No immediate action required.",
                "priority": "info"
            })

        return recommendations

    def generate_ai_agent_summary(
        self,
        test_results: list[TestResult],
        log_summary: dict[str, Any] | None = None,
        container_logs: dict[str, list[LogEntry]] | None = None
    ) -> dict[str, Any]:
        """Generate a structured summary optimized for AI agent consumption."""
        from datetime import timedelta
        timestamp = datetime.utcnow()

        # Core metrics for AI analysis
        total_tests = len(test_results)
        passed_tests = sum(1 for result in test_results if result.success)
        failed_tests = total_tests - passed_tests

        # System health score (0-100)
        health_score = self._calculate_health_score(test_results, log_summary)

        # Critical issues detection
        critical_issues = self._detect_critical_issues(test_results, log_summary, container_logs)

        # Action items for AI agent
        action_items = self._generate_ai_action_items(test_results, log_summary, critical_issues)

        ai_summary = {
            "meta": {
                "report_type": "ai_agent_daily_summary",
                "timestamp": timestamp.isoformat(),
                "format_version": "1.0",
                "next_run_expected": (timestamp.replace(hour=6, minute=0, second=0) +
                                    timedelta(days=1)).isoformat()
            },
            "system_health": {
                "overall_score": health_score,
                "status": self._get_health_status(health_score),
                "test_summary": {
                    "total_tests": total_tests,
                    "passed": passed_tests,
                    "failed": failed_tests,
                    "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0
                },
                "infrastructure": {
                    "containers_monitored": len(container_logs) if container_logs else 0,
                    "log_errors": log_summary.get("total_errors", 0) if log_summary else 0,
                    "critical_container_issues": len([c for c in (container_logs or {}).values()
                                                    if any(log.level == "ERROR" for log in c)])
                }
            },
            "critical_issues": critical_issues,
            "action_items": action_items,
            "trends": self._analyze_trends(test_results),
            "telegram_ready": {
                "urgent_alert": health_score < 70 or len(critical_issues) > 0,
                "summary_message": self._generate_telegram_summary(health_score, critical_issues, total_tests, passed_tests),
                "detailed_report_available": True
            },
            "ai_analysis": {
                "requires_human_intervention": health_score < 50 or any(issue["severity"] == "critical" for issue in critical_issues),
                "monitoring_confidence": self._calculate_monitoring_confidence(test_results),
                "recommended_check_frequency": "daily" if health_score > 80 else "hourly"
            }
        }

        # Save AI-optimized report
        if self.config.ai_agent.enable_structured_output:
            ai_path = self.reports_dir / f"ai_summary_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
            with open(ai_path, 'w') as f:
                json.dump(ai_summary, f, indent=2, default=str)

            # Also save as "latest" for easy AI agent access
            latest_path = self.reports_dir / "latest_ai_summary.json"
            with open(latest_path, 'w') as f:
                json.dump(ai_summary, f, indent=2, default=str)

        logger.info("Generated AI agent summary",
                   health_score=health_score,
                   critical_issues=len(critical_issues),
                   urgent_alert=ai_summary["telegram_ready"]["urgent_alert"])

        return ai_summary

    def _calculate_health_score(self, test_results: list[TestResult], log_summary: dict[str, Any] | None) -> int:
        """Calculate overall system health score (0-100)."""
        if not test_results:
            return 50  # Neutral score if no data

        # Base score from test success rate
        success_rate = sum(1 for r in test_results if r.success) / len(test_results)
        base_score = success_rate * 80  # 80 points max from tests

        # Penalty for log errors
        log_penalty = 0
        if log_summary and log_summary.get("total_errors", 0) > 0:
            error_count = log_summary["total_errors"]
            log_penalty = min(error_count * 2, 20)  # Up to 20 points penalty

        # Bonus for consistent performance
        consistency_bonus = 0
        if success_rate > 0.95:
            consistency_bonus = 20
        elif success_rate > 0.9:
            consistency_bonus = 10

        final_score = max(0, min(100, base_score + consistency_bonus - log_penalty))
        return int(final_score)

    def _get_health_status(self, health_score: int) -> str:
        """Convert health score to status string."""
        if health_score >= 90:
            return "excellent"
        elif health_score >= 75:
            return "good"
        elif health_score >= 50:
            return "warning"
        else:
            return "critical"

    def _detect_critical_issues(
        self,
        test_results: list[TestResult],
        log_summary: dict[str, Any] | None,
        container_logs: dict[str, list[LogEntry]] | None
    ) -> list[dict[str, Any]]:
        """Detect critical issues requiring immediate attention."""
        issues = []

        # Failed critical tests
        critical_failures = [r for r in test_results if not r.success and
                           r.metadata.get("priority") == "critical"]
        if critical_failures:
            issues.append({
                "type": "critical_test_failures",
                "severity": "critical",
                "count": len(critical_failures),
                "description": f"{len(critical_failures)} critical tests failed",
                "tests": [r.test_name for r in critical_failures],
                "requires_immediate_action": True
            })

        # High error volume
        if log_summary and log_summary.get("total_errors", 0) > 50:
            issues.append({
                "type": "high_error_volume",
                "severity": "high",
                "count": log_summary["total_errors"],
                "description": f"Excessive error volume: {log_summary['total_errors']} errors",
                "requires_immediate_action": log_summary["total_errors"] > 100
            })

        # Container issues
        if container_logs:
            for container, logs in container_logs.items():
                error_logs = [log for log in logs if log.level == "ERROR"]
                if len(error_logs) > 10:
                    issues.append({
                        "type": "container_errors",
                        "severity": "high",
                        "container": container,
                        "count": len(error_logs),
                        "description": f"Container {container} has {len(error_logs)} errors",
                        "requires_immediate_action": len(error_logs) > 25
                    })

        return issues

    def _generate_ai_action_items(
        self,
        test_results: list[TestResult],
        log_summary: dict[str, Any] | None,
        critical_issues: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate specific action items for the AI agent."""
        actions = []

        if critical_issues:
            actions.append({
                "priority": "immediate",
                "action": "alert_ops_team",
                "description": "Critical issues detected - notify operations team",
                "data": {"issue_count": len(critical_issues), "issues": critical_issues}
            })

        failed_tests = [r for r in test_results if not r.success]
        if failed_tests:
            actions.append({
                "priority": "high",
                "action": "investigate_test_failures",
                "description": f"Investigate {len(failed_tests)} failed tests",
                "data": {"failed_tests": [r.test_name for r in failed_tests]}
            })

        if log_summary and log_summary.get("total_errors", 0) > 20:
            actions.append({
                "priority": "medium",
                "action": "analyze_log_patterns",
                "description": "Analyze log error patterns for recurring issues",
                "data": {"error_count": log_summary["total_errors"]}
            })

        if not actions:
            actions.append({
                "priority": "low",
                "action": "continue_monitoring",
                "description": "No issues detected - continue regular monitoring",
                "data": {"next_check": "scheduled"}
            })

        return actions

    def _analyze_trends(self, test_results: list[TestResult]) -> dict[str, Any]:
        """Analyze trends in test results."""
        if len(test_results) < 2:
            return {"trend": "insufficient_data"}

        # Simple trend analysis based on recent vs older results
        mid_point = len(test_results) // 2
        recent_results = test_results[mid_point:]
        older_results = test_results[:mid_point]

        recent_success_rate = sum(1 for r in recent_results if r.success) / len(recent_results)
        older_success_rate = sum(1 for r in older_results if r.success) / len(older_results)

        trend_change = recent_success_rate - older_success_rate

        return {
            "trend": "improving" if trend_change > 0.05 else "declining" if trend_change < -0.05 else "stable",
            "change_magnitude": abs(trend_change),
            "recent_success_rate": recent_success_rate * 100,
            "trend_confidence": "high" if abs(trend_change) > 0.1 else "medium" if abs(trend_change) > 0.05 else "low"
        }

    def _generate_telegram_summary(self, health_score: int, critical_issues: list[dict], total_tests: int, passed_tests: int) -> str:
        """Generate a concise message suitable for Telegram notification."""
        status_emoji = "🟢" if health_score >= 90 else "🟡" if health_score >= 75 else "🔴"

        if critical_issues:
            return f"{status_emoji} ALERT: {len(critical_issues)} critical issues detected. Health: {health_score}/100. Tests: {passed_tests}/{total_tests} passed."
        else:
            return f"{status_emoji} System healthy. Score: {health_score}/100. Tests: {passed_tests}/{total_tests} passed. All good!"

    def _calculate_monitoring_confidence(self, test_results: list[TestResult]) -> str:
        """Calculate confidence in monitoring results."""
        if len(test_results) < 5:
            return "low"
        elif len(test_results) < 20:
            return "medium"
        else:
            return "high"
