"""AI Monitoring Lead - Orchestrates daily monitoring tasks and analysis."""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import structlog

from ..ui_testing import UITestRunner, TestManager
from ..log_collector import BashDockerLogCollector
from ..reporting import ReportGenerator, IncidentTracker
from ..notifications import TelegramNotifier
from ..config import get_config

logger = structlog.get_logger(__name__)


class AIMonitoringLead:
    """AI agent that orchestrates daily monitoring activities."""
    
    def __init__(self):
        """Initialize the AI Monitoring Lead."""
        self.config = get_config()
        self.test_runner = UITestRunner()
        self.test_manager = TestManager()
        self.log_collector = BashDockerLogCollector()
        self.report_generator = ReportGenerator()
        self.incident_tracker = IncidentTracker()
        self.telegram = TelegramNotifier()
        
        logger.info("AI Monitoring Lead initialized")
    
    async def execute_daily_monitoring(self) -> Dict[str, Any]:
        """Execute complete daily monitoring workflow.
        
        This is the main entry point for the AI agent to:
        1. Run all UI tests
        2. Collect logs from all containers
        3. Analyze results
        4. Generate report
        5. Send Telegram notification
        
        Returns:
            Complete monitoring report with all data
        """
        logger.info("Starting daily monitoring workflow", timestamp=datetime.utcnow().isoformat())
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "date": datetime.utcnow().date().isoformat(),
            "monitoring_lead": "AI Agent",
            "status": "in_progress"
        }
        
        try:
            # Step 1: Run UI tests
            logger.info("Step 1: Running UI tests")
            ui_test_results = await self._run_ui_tests()
            report["ui_tests"] = ui_test_results
            
            # Step 2: Collect Docker logs
            logger.info("Step 2: Collecting Docker logs")
            log_results = await self._collect_container_logs()
            report["container_logs"] = log_results
            
            # Step 3: Analyze results
            logger.info("Step 3: Analyzing results")
            analysis = await self._analyze_monitoring_data(ui_test_results, log_results)
            report["analysis"] = analysis
            
            # Step 4: Generate incidents if needed
            logger.info("Step 4: Processing incidents")
            incidents = await self._process_incidents(analysis)
            report["incidents"] = incidents
            
            # Step 5: Generate summary
            logger.info("Step 5: Generating summary")
            summary = self._generate_summary(report)
            report["summary"] = summary
            
            # Step 6: Send notifications
            logger.info("Step 6: Sending notifications")
            notification_sent = await self._send_notifications(summary)
            report["notification_sent"] = notification_sent
            
            report["status"] = "completed"
            report["completion_time"] = datetime.utcnow().isoformat()
            
            # Save report to file
            await self._save_report(report)
            
            logger.info("Daily monitoring workflow completed", 
                       ui_tests_run=len(ui_test_results.get("test_results", [])),
                       containers_monitored=len(log_results.get("containers", [])),
                       incidents_created=len(incidents))
            
        except Exception as e:
            logger.error("Daily monitoring workflow failed", error=str(e))
            report["status"] = "failed"
            report["error"] = str(e)
            
            # Send failure notification
            await self.telegram.send_critical_alert({
                "service": "AI Monitoring Lead",
                "issue": "Daily monitoring workflow failed",
                "details": str(e),
                "timestamp": datetime.utcnow().isoformat(),
                "action": "Manual investigation required"
            })
        
        return report
    
    async def _run_ui_tests(self) -> Dict[str, Any]:
        """Run all configured UI tests."""
        try:
            # Load all tests
            tests = self.test_manager.load_all_tests()
            production_tests = self.test_manager.filter_by_environment(tests, "production")
            
            if not production_tests:
                logger.warning("No production UI tests configured")
                return {"test_results": [], "summary": {"total": 0, "passed": 0, "failed": 0}}
            
            # Run tests
            await self.test_runner.start()
            results = await self.test_runner.run_test_suite(production_tests)
            await self.test_runner.stop()
            
            # Generate test report
            test_report = self.report_generator.generate_test_report(results)
            
            return test_report
            
        except Exception as e:
            logger.error("Failed to run UI tests", error=str(e))
            return {"error": str(e), "test_results": []}
    
    async def _collect_container_logs(self) -> Dict[str, Any]:
        """Collect logs from all Docker containers."""
        try:
            # Collect logs for last 24 hours
            container_logs = self.log_collector.collect_logs_for_timeframe(
                containers=None,  # Auto-discover all containers
                hours_back=24
            )
            
            # Get error summary
            error_summary = self.log_collector.get_error_summary(container_logs)
            
            # Get container info
            container_info = self.log_collector.get_container_info()
            
            return {
                "containers": list(container_logs.keys()),
                "container_info": container_info,
                "total_logs": sum(len(logs) for logs in container_logs.values()),
                "error_summary": error_summary,
                "collection_time": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error("Failed to collect container logs", error=str(e))
            return {"error": str(e), "containers": []}
    
    async def _analyze_monitoring_data(
        self, 
        ui_results: Dict[str, Any], 
        log_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze monitoring data for patterns and issues."""
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "health_status": "healthy",
            "issues_detected": [],
            "recommendations": [],
            "metrics": {}
        }
        
        # Analyze UI test results
        if ui_results.get("summary"):
            ui_summary = ui_results["summary"]
            analysis["metrics"]["ui_test_success_rate"] = ui_summary.get("success_rate", 0)
            
            if ui_summary.get("failed", 0) > 0:
                analysis["health_status"] = "degraded"
                analysis["issues_detected"].append({
                    "type": "ui_test_failures",
                    "severity": "high" if ui_summary.get("failed", 0) > 2 else "medium",
                    "count": ui_summary.get("failed", 0),
                    "details": "UI tests are failing, user experience may be impacted"
                })
                analysis["recommendations"].append(
                    "Investigate UI test failures immediately to ensure user functionality"
                )
        
        # Analyze container logs
        if log_results.get("error_summary"):
            error_summary = log_results["error_summary"]
            analysis["metrics"]["total_errors"] = error_summary.get("total_errors", 0)
            analysis["metrics"]["containers_with_errors"] = error_summary.get("containers_with_errors", 0)
            
            if error_summary.get("critical_issues"):
                analysis["health_status"] = "critical"
                for issue in error_summary["critical_issues"]:
                    analysis["issues_detected"].append({
                        "type": "critical_error",
                        "severity": "critical",
                        "container": issue.get("container"),
                        "message": issue.get("message"),
                        "timestamp": issue.get("timestamp")
                    })
                analysis["recommendations"].append(
                    "Critical errors detected in containers - immediate action required"
                )
            elif error_summary.get("total_errors", 0) > 100:
                analysis["health_status"] = "degraded"
                analysis["recommendations"].append(
                    "High error rate detected - review container logs for patterns"
                )
        
        # Calculate overall health score
        health_score = self._calculate_health_score(analysis)
        analysis["health_score"] = health_score
        
        return analysis
    
    def _calculate_health_score(self, analysis: Dict[str, Any]) -> float:
        """Calculate overall system health score (0-100)."""
        score = 100.0
        
        # Deduct for UI test failures
        ui_success_rate = analysis["metrics"].get("ui_test_success_rate", 100)
        score -= (100 - ui_success_rate) * 0.3  # 30% weight for UI tests
        
        # Deduct for errors
        total_errors = analysis["metrics"].get("total_errors", 0)
        if total_errors > 0:
            error_penalty = min(30, total_errors / 10)  # Max 30 point penalty
            score -= error_penalty
        
        # Deduct for critical issues
        critical_count = sum(1 for issue in analysis["issues_detected"] 
                            if issue.get("severity") == "critical")
        score -= critical_count * 20  # 20 points per critical issue
        
        return max(0, min(100, score))
    
    async def _process_incidents(self, analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create incidents for detected issues."""
        incidents = []
        
        for issue in analysis.get("issues_detected", []):
            if issue.get("severity") in ["critical", "high"]:
                incident = await self.incident_tracker.create_incident(
                    title=f"{issue['type']}: {issue.get('details', 'Issue detected')}",
                    description=json.dumps(issue, indent=2),
                    severity=issue["severity"],
                    source="ai_monitoring_lead",
                    metadata=issue
                )
                incidents.append(incident)
                logger.info("Created incident", incident_id=incident["id"], severity=issue["severity"])
        
        return incidents
    
    def _generate_summary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Generate executive summary for the report."""
        ui_tests = report.get("ui_tests", {}).get("summary", {})
        log_summary = report.get("container_logs", {}).get("error_summary", {})
        analysis = report.get("analysis", {})
        
        all_healthy = (
            ui_tests.get("failed", 0) == 0 and
            log_summary.get("total_errors", 0) < 10 and
            analysis.get("health_status") != "critical"
        )
        
        summary = {
            "date": report["date"],
            "all_healthy": all_healthy,
            "health_status": analysis.get("health_status", "unknown"),
            "health_score": analysis.get("health_score", 0),
            "ui_tests_total": ui_tests.get("total", 0),
            "ui_tests_passed": ui_tests.get("passed", 0),
            "ui_tests_failed": ui_tests.get("failed", 0),
            "containers_monitored": len(report.get("container_logs", {}).get("containers", [])),
            "total_errors": log_summary.get("total_errors", 0),
            "critical_issues": log_summary.get("critical_issues", []),
            "failed_tests": [
                test for test in report.get("ui_tests", {}).get("test_results", [])
                if not test.get("success")
            ],
            "incidents_created": len(report.get("incidents", [])),
            "recommendations": analysis.get("recommendations", []),
            "uptime_percentage": 100.0 if all_healthy else max(50, analysis.get("health_score", 0))
        }
        
        return summary
    
    async def _send_notifications(self, summary: Dict[str, Any]) -> bool:
        """Send notifications based on summary."""
        # Always send daily report
        notification_sent = await self.telegram.send_daily_report(summary)
        
        # Send additional alerts for critical issues
        if not summary.get("all_healthy"):
            if summary.get("health_status") == "critical":
                await self.telegram.send_critical_alert({
                    "service": "PitchAI Monitoring",
                    "issue": f"Critical issues detected - Health score: {summary.get('health_score', 0):.1f}",
                    "details": f"Failed tests: {summary.get('ui_tests_failed', 0)}, Errors: {summary.get('total_errors', 0)}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "action": "Review monitoring dashboard immediately"
                })
            
            if summary.get("failed_tests"):
                await self.telegram.send_test_failure_summary(summary["failed_tests"])
        
        return notification_sent
    
    async def _save_report(self, report: Dict[str, Any]) -> None:
        """Save the complete report to file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"reports/ai_monitoring_report_{timestamp}.json"
        
        try:
            with open(filename, "w") as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Report saved", filename=filename)
        except Exception as e:
            logger.error("Failed to save report", error=str(e))