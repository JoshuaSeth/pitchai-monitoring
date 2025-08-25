"""Task coordination for orchestrating monitoring workflows."""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
import structlog

from ..ui_testing.runner import UITestRunner, TestResult
from ..ui_testing.test_manager import TestManager
from ..log_collector.docker_logs import DockerLogCollector
from ..log_collector.log_processor import LogProcessor
from ..reporting.report_generator import ReportGenerator
from ..reporting.incident_tracker import IncidentTracker
from .job_scheduler import JobScheduler
from ..config import get_config


logger = structlog.get_logger(__name__)


class TaskCoordinator:
    """Coordinates monitoring tasks and workflows."""
    
    def __init__(self):
        self.config = get_config()
        self.scheduler = JobScheduler()
        self.test_manager = TestManager()
        self.log_processor = LogProcessor()
        self.report_generator = ReportGenerator()
        self.incident_tracker = IncidentTracker()
        
        # Task execution tracking
        self.running_tasks: Dict[str, Dict[str, Any]] = {}
        self.task_history: List[Dict[str, Any]] = []
    
    async def start(self):
        """Start the task coordinator and scheduler."""
        await self.scheduler.start()
        await self._setup_default_jobs()
        logger.info("Task coordinator started")
    
    async def stop(self):
        """Stop the task coordinator and scheduler."""
        await self.scheduler.stop()
        logger.info("Task coordinator stopped")
    
    async def _setup_default_jobs(self):
        """Setup default monitoring jobs based on configuration."""
        # AI Agent Daily Test Suite (Production optimized)
        self.scheduler.add_cron_job(
            job_id="ai_agent_daily_tests",
            func=self.run_ai_agent_daily_workflow,
            cron_expression=self.config.test_schedule_cron,  # Daily at 6 AM
            description="AI Agent daily monitoring workflow"
        )
        
        # Log Collection Job (Less frequent for daily monitoring)
        self.scheduler.add_interval_job(
            job_id="log_collection",
            func=self.collect_container_logs,
            seconds=self.config.log_collection_interval,  # 1 hour
            description="Collect Docker container logs"
        )
        
        # AI Agent Daily Report Generation
        daily_report_hour, daily_report_minute = self.config.daily_report_time.split(":")
        daily_report_cron = f"{daily_report_minute} {daily_report_hour} * * *"
        self.scheduler.add_cron_job(
            job_id="ai_agent_daily_report",
            func=self.generate_ai_agent_report,
            cron_expression=daily_report_cron,  # 6:30 AM daily
            description="Generate AI agent optimized daily report"
        )
        
        logger.info("Setup AI agent monitoring jobs", 
                   test_schedule=self.config.test_schedule_cron,
                   report_schedule=daily_report_cron)
    
    async def run_ui_test_suite(self) -> Dict[str, Any]:
        """Execute the complete UI test suite."""
        task_id = f"ui_tests_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting UI test suite", task_id=task_id)
        
        self.running_tasks[task_id] = {
            "type": "ui_tests",
            "start_time": datetime.utcnow(),
            "status": "running"
        }
        
        try:
            # Load test configurations
            test_configs = self.test_manager.load_all_tests()
            if not test_configs:
                logger.warning("No test configurations found")
                result = {
                    "task_id": task_id,
                    "success": True,
                    "message": "No tests to run",
                    "test_results": []
                }
                self._complete_task(task_id, result)
                return result
            
            # Filter tests for current environment
            filtered_tests = self.test_manager.filter_tests_by_environment(
                test_configs, self.config.environment
            )
            
            # Run tests
            async with UITestRunner() as runner:
                test_results = await runner.run_test_suite(filtered_tests)
            
            # Generate report
            report_data = self.report_generator.generate_test_results_report(test_results)
            
            # Handle failures
            incidents_created = []
            for result in test_results:
                if not result.success:
                    incident = await self._handle_test_failure(result)
                    if incident:
                        incidents_created.append(incident.incident_id)
            
            result = {
                "task_id": task_id,
                "success": True,
                "test_count": len(test_results),
                "passed": sum(1 for r in test_results if r.success),
                "failed": sum(1 for r in test_results if not r.success),
                "report_file": report_data.get("report_name"),
                "incidents_created": incidents_created,
                "test_results": [r.to_dict() for r in test_results]
            }
            
            self._complete_task(task_id, result)
            
            logger.info("Completed UI test suite", 
                       task_id=task_id,
                       passed=result["passed"],
                       failed=result["failed"])
            
            return result
            
        except Exception as e:
            error_result = {
                "task_id": task_id,
                "success": False,
                "error": str(e)
            }
            self._complete_task(task_id, error_result)
            logger.error("UI test suite failed", task_id=task_id, error=str(e))
            return error_result
    
    async def collect_container_logs(self, hours_back: int = 1) -> Dict[str, Any]:
        """Collect logs from Docker containers."""
        task_id = f"log_collection_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting log collection", task_id=task_id, hours_back=hours_back)
        
        self.running_tasks[task_id] = {
            "type": "log_collection",
            "start_time": datetime.utcnow(),
            "status": "running"
        }
        
        try:
            from ..log_collector.docker_logs import BashDockerLogCollector
            collector = BashDockerLogCollector()
            container_logs = collector.collect_logs_for_timeframe(hours_back=hours_back)
            
            # Process and analyze logs
            log_summary = self.log_processor.generate_log_summary(container_logs)
            
            # Save logs to file
            log_file = self.log_processor.save_logs_to_file(container_logs)
            
            result = {
                "task_id": task_id,
                "success": True,
                "containers_checked": len(container_logs),
                "total_logs": sum(len(logs) for logs in container_logs.values()),
                "errors_found": log_summary.get("total_errors", 0),
                "warnings_found": log_summary.get("total_warnings", 0),
                "log_file": log_file,
                "summary": log_summary
            }
            
            self._complete_task(task_id, result)
            
            logger.info("Completed log collection", 
                       task_id=task_id,
                       total_logs=result["total_logs"],
                       errors=result["errors_found"])
            
            return result
            
        except Exception as e:
            error_result = {
                "task_id": task_id,
                "success": False,
                "error": str(e)
            }
            self._complete_task(task_id, error_result)
            logger.error("Log collection failed", task_id=task_id, error=str(e))
            return error_result
    
    async def generate_daily_report(self) -> Dict[str, Any]:
        """Generate daily monitoring report."""
        task_id = f"daily_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting daily report generation", task_id=task_id)
        
        self.running_tasks[task_id] = {
            "type": "daily_report",
            "start_time": datetime.utcnow(),
            "status": "running"
        }
        
        try:
            # Get recent test results from task history
            recent_test_results = []
            for task in self.task_history:
                if (task.get("type") == "ui_tests" and 
                    task.get("success") and 
                    "test_results" in task):
                    recent_test_results.extend(task["test_results"])
            
            # Get recent log summary
            recent_log_summary = None
            for task in reversed(self.task_history):
                if (task.get("type") == "log_collection" and 
                    task.get("success") and 
                    "summary" in task):
                    recent_log_summary = task["summary"]
                    break
            
            # Convert dict test results back to TestResult objects
            test_result_objects = []
            for result_dict in recent_test_results:
                test_result = TestResult(
                    test_name=result_dict["test_name"],
                    success=result_dict["success"],
                    duration=result_dict["duration"],
                    error=result_dict.get("error"),
                    screenshot_path=result_dict.get("screenshot_path"),
                    metadata=result_dict.get("metadata", {})
                )
                test_result.timestamp = result_dict["timestamp"]
                test_result_objects.append(test_result)
            
            # Generate daily summary
            daily_summary = self.report_generator.generate_daily_summary(
                test_result_objects, recent_log_summary
            )
            
            result = {
                "task_id": task_id,
                "success": True,
                "summary": daily_summary,
                "test_runs_analyzed": len(test_result_objects),
                "issues_found": len(daily_summary.get("issues", []))
            }
            
            self._complete_task(task_id, result)
            
            logger.info("Completed daily report generation", 
                       task_id=task_id,
                       issues=result["issues_found"])
            
            return result
            
        except Exception as e:
            error_result = {
                "task_id": task_id,
                "success": False,
                "error": str(e)
            }
            self._complete_task(task_id, error_result)
            logger.error("Daily report generation failed", task_id=task_id, error=str(e))
            return error_result
    
    async def _handle_test_failure(self, test_result: TestResult) -> Optional[Any]:
        """Handle a failed test by creating incident and correlating logs."""
        try:
            # Collect recent logs for correlation
            from ..log_collector.docker_logs import BashDockerLogCollector
            collector = BashDockerLogCollector()
            container_logs = collector.collect_logs_for_timeframe(hours_back=1)
            
            # Correlate logs with failure time
            failure_time = datetime.fromisoformat(test_result.timestamp)
            correlation_data = self.log_processor.correlate_with_test_failure(
                container_logs, failure_time
            )
            
            # Create incident
            incident = self.incident_tracker.create_incident(
                test_name=test_result.test_name,
                failure_time=failure_time,
                error_message=test_result.error,
                screenshot_path=test_result.screenshot_path
            )
            
            # Generate incident report
            incident_report = self.report_generator.generate_incident_report(
                test_result, correlation_data, incident.incident_id
            )
            
            logger.info("Created incident for test failure", 
                       incident_id=incident.incident_id,
                       test_name=test_result.test_name)
            
            return incident
            
        except Exception as e:
            logger.error("Failed to handle test failure", 
                        test_name=test_result.test_name,
                        error=str(e))
            return None
    
    def _complete_task(self, task_id: str, result: Dict[str, Any]):
        """Mark a task as complete and add to history."""
        if task_id in self.running_tasks:
            task_info = self.running_tasks[task_id]
            task_info["end_time"] = datetime.utcnow()
            task_info["duration"] = (task_info["end_time"] - task_info["start_time"]).total_seconds()
            task_info["status"] = "completed"
            task_info.update(result)
            
            # Move to history
            self.task_history.append(task_info)
            del self.running_tasks[task_id]
            
            # Keep only last 100 tasks in history
            if len(self.task_history) > 100:
                self.task_history = self.task_history[-100:]
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific task."""
        if task_id in self.running_tasks:
            return self.running_tasks[task_id]
        
        for task in self.task_history:
            if task.get("task_id") == task_id:
                return task
        
        return None
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status."""
        scheduler_status = self.scheduler.get_scheduler_status()
        
        return {
            "scheduler": scheduler_status,
            "running_tasks": len(self.running_tasks),
            "completed_tasks": len(self.task_history),
            "recent_tasks": self.task_history[-5:] if self.task_history else []
        }
    
    async def run_ai_agent_daily_workflow(self) -> Dict[str, Any]:
        """Execute the complete AI agent daily monitoring workflow."""
        task_id = f"ai_daily_workflow_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting AI agent daily workflow", task_id=task_id)
        
        self.running_tasks[task_id] = {
            "type": "ai_daily_workflow",
            "start_time": datetime.utcnow(),
            "status": "running"
        }
        
        try:
            # Step 1: Run UI tests
            ui_test_result = await self.run_ui_test_suite()
            
            # Step 2: Collect fresh container logs
            log_collection_result = await self.collect_container_logs(hours_back=24)
            
            # Step 3: Generate AI agent summary
            ai_report_result = await self.generate_ai_agent_report()
            
            result = {
                "task_id": task_id,
                "success": True,
                "workflow_steps": {
                    "ui_tests": ui_test_result,
                    "log_collection": log_collection_result,
                    "ai_report": ai_report_result
                },
                "summary": {
                    "tests_passed": ui_test_result.get("passed", 0),
                    "tests_failed": ui_test_result.get("failed", 0),
                    "log_errors": log_collection_result.get("errors_found", 0),
                    "urgent_alert": ai_report_result.get("urgent_alert", False)
                }
            }
            
            self._complete_task(task_id, result)
            
            logger.info("Completed AI agent daily workflow", 
                       task_id=task_id,
                       passed=result["summary"]["tests_passed"],
                       failed=result["summary"]["tests_failed"],
                       urgent=result["summary"]["urgent_alert"])
            
            return result
            
        except Exception as e:
            error_result = {
                "task_id": task_id,
                "success": False,
                "error": str(e)
            }
            self._complete_task(task_id, error_result)
            logger.error("AI agent daily workflow failed", task_id=task_id, error=str(e))
            return error_result
    
    async def generate_ai_agent_report(self) -> Dict[str, Any]:
        """Generate AI agent optimized monitoring report."""
        task_id = f"ai_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("Starting AI agent report generation", task_id=task_id)
        
        self.running_tasks[task_id] = {
            "type": "ai_report",
            "start_time": datetime.utcnow(),
            "status": "running"
        }
        
        try:
            # Get recent test results from task history
            recent_test_results = []
            for task in self.task_history:
                if (task.get("type") in ["ui_tests", "ai_daily_workflow"] and 
                    task.get("success") and 
                    "test_results" in task):
                    if task.get("type") == "ai_daily_workflow":
                        # Extract from workflow
                        ui_results = task.get("workflow_steps", {}).get("ui_tests", {})
                        if "test_results" in ui_results:
                            recent_test_results.extend(ui_results["test_results"])
                    else:
                        recent_test_results.extend(task["test_results"])
            
            # Get recent log data
            recent_log_summary = None
            container_logs = None
            for task in reversed(self.task_history):
                if (task.get("type") == "log_collection" and 
                    task.get("success") and 
                    "summary" in task):
                    recent_log_summary = task["summary"]
                    break
            
            # Collect fresh container logs for AI analysis
            try:
                from ..log_collector.docker_logs import BashDockerLogCollector
                collector = BashDockerLogCollector()
                container_logs = collector.collect_logs_for_timeframe(hours_back=24)
                if not recent_log_summary and container_logs:
                    recent_log_summary = collector.get_error_summary(container_logs)
            except Exception as log_error:
                logger.warning("Failed to collect fresh logs for AI report", error=str(log_error))
            
            # Convert dict test results back to TestResult objects
            test_result_objects = []
            for result_dict in recent_test_results:
                test_result = TestResult(
                    test_name=result_dict["test_name"],
                    success=result_dict["success"],
                    duration=result_dict["duration"],
                    error=result_dict.get("error"),
                    screenshot_path=result_dict.get("screenshot_path"),
                    metadata=result_dict.get("metadata", {})
                )
                test_result.timestamp = result_dict["timestamp"]
                test_result_objects.append(test_result)
            
            # Generate AI agent summary
            ai_summary = self.report_generator.generate_ai_agent_summary(
                test_result_objects, recent_log_summary, container_logs
            )
            
            result = {
                "task_id": task_id,
                "success": True,
                "ai_summary": ai_summary,
                "health_score": ai_summary["system_health"]["overall_score"],
                "urgent_alert": ai_summary["telegram_ready"]["urgent_alert"],
                "critical_issues": len(ai_summary["critical_issues"]),
                "telegram_message": ai_summary["telegram_ready"]["summary_message"]
            }
            
            self._complete_task(task_id, result)
            
            logger.info("Completed AI agent report generation", 
                       task_id=task_id,
                       health_score=result["health_score"],
                       urgent_alert=result["urgent_alert"])
            
            return result
            
        except Exception as e:
            error_result = {
                "task_id": task_id,
                "success": False,
                "error": str(e)
            }
            self._complete_task(task_id, error_result)
            logger.error("AI agent report generation failed", task_id=task_id, error=str(e))
            return error_result