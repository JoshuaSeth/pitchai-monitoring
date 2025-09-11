"""Main entry point for the monitoring system."""

import asyncio
import sys
from pathlib import Path

import structlog
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse

from monitoring.ai_agent import AIMonitoringLead
from monitoring.config import get_config
from monitoring.scheduler.task_coordinator import TaskCoordinator

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global coordinator instance
coordinator: TaskCoordinator = None
app = FastAPI(title="Production Monitoring System", version="0.1.0")


@app.on_event("startup")
async def startup_event():
    """Initialize the monitoring system on startup."""
    global coordinator
    coordinator = TaskCoordinator()
    await coordinator.start()
    logger.info("Monitoring system started")
    
    # Start Python scheduler as alternative to cron
    try:
        from python_scheduler import start_scheduler
        start_scheduler()
        logger.info("Python scheduler started as cron alternative")
    except Exception as e:
        logger.warning(f"Could not start Python scheduler: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global coordinator
    if coordinator:
        await coordinator.stop()
    logger.info("Monitoring system stopped")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "healthy", "service": "monitoring", "restart_time": "2025-08-26T05:35:00Z"}


@app.get("/endpoints")
async def list_endpoints():
    """List all available API endpoints for testing."""
    return {
        "service": "PitchAI Claude Monitoring System",
        "endpoints": {
            "health": {
                "GET /": "Health check",
                "GET /status": "System status", 
                "GET /health/docker": "Docker accessibility check",
                "GET /debug/env": "Environment debug info"
            },
            "monitoring": {
                "GET|POST /run/claude-monitoring": "🤖 Trigger Claude AI monitoring (main feature)",
                "GET|POST /run/autopar-monitoring": "🎯 Trigger Autopar staging monitoring",
                "GET|POST /run/quickchat-monitoring": "💬 Trigger Quickchat system monitoring",
                "POST /run/ai-monitoring": "Legacy AI monitoring workflow",
                "POST /run/ui-tests": "Run UI test suite",
                "POST /run/log-collection": "Collect container logs",
                "POST /run/daily-report": "Generate daily report",
                "POST /run/ai-workflow": "Run AI workflow",
                "POST /run/ai-report": "Generate AI report"
            },
            "reports": {
                "GET /reports/latest-ai-summary": "Get latest AI summary"
            },
            "tasks": {
                "GET /tasks/{task_id}": "Get task status"
            }
        },
        "examples": {
            "trigger_claude_monitoring": "GET|POST /run/claude-monitoring?hours=2",
            "trigger_autopar_monitoring": "GET|POST /run/autopar-monitoring?hours=4",
            "trigger_quickchat_monitoring": "GET|POST /run/quickchat-monitoring?hours=4",
            "health_check": "GET /",
            "system_status": "GET /status"
        },
        "python_schedule": {
            "main_monitoring": {
                "morning": "04:00 UTC (05:00 Amsterdam)",
                "afternoon": "11:00 UTC (12:00 Amsterdam)"
            },
            "autopar_monitoring": {
                "morning": "04:15 UTC (05:15 Amsterdam)",
                "afternoon": "11:15 UTC (12:15 Amsterdam)"
            },
            "quickchat_monitoring": {
                "morning": "04:30 UTC (05:30 Amsterdam)",
                "afternoon": "11:30 UTC (12:30 Amsterdam)"
            }
        }
    }


@app.get("/debug/env")
async def debug_environment():
    """Debug environment variables (for troubleshooting only)."""
    import os
    
    env_info = {
        "claude_token_configured": bool(os.getenv('CLAUDE_CODE_OAUTH_TOKEN')),
        "claude_token_prefix": os.getenv('CLAUDE_CODE_OAUTH_TOKEN', '')[:20] + '...' if os.getenv('CLAUDE_CODE_OAUTH_TOKEN') else 'Not set',
        "telegram_token_configured": bool(os.getenv('TELEGRAM_BOT_TOKEN')),
        "telegram_chat_configured": bool(os.getenv('TELEGRAM_CHAT_ID')),
        "monitoring_env": os.getenv('MONITORING_ENV', 'not set'),
        "path_env": os.getenv('PATH', '').split(':')[:5]  # First 5 PATH entries
    }
    
    return env_info


@app.get("/status")
async def get_status():
    """Get system status."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    status = coordinator.get_system_status()
    return status


@app.post("/run/ui-tests")
async def run_ui_tests(background_tasks: BackgroundTasks):
    """Trigger UI test suite manually."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    background_tasks.add_task(coordinator.run_ui_test_suite)
    return {"message": "UI test suite started", "status": "running"}


@app.post("/run/log-collection")
async def run_log_collection(background_tasks: BackgroundTasks, hours_back: int = 1):
    """Trigger log collection manually."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    background_tasks.add_task(coordinator.collect_container_logs, hours_back)
    return {"message": "Log collection started", "status": "running", "hours_back": hours_back}


@app.post("/run/daily-report")
async def run_daily_report(background_tasks: BackgroundTasks):
    """Generate daily report manually."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    background_tasks.add_task(coordinator.generate_daily_report)
    return {"message": "Daily report generation started", "status": "running"}


@app.post("/run/ai-workflow")
async def run_ai_workflow(background_tasks: BackgroundTasks):
    """Trigger AI agent daily workflow manually."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    background_tasks.add_task(coordinator.run_ai_agent_daily_workflow)
    return {"message": "AI agent daily workflow started", "status": "running"}


@app.post("/run/ai-report")
async def run_ai_report(background_tasks: BackgroundTasks):
    """Generate AI agent report manually."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    background_tasks.add_task(coordinator.generate_ai_agent_report)
    return {"message": "AI agent report generation started", "status": "running"}


@app.get("/reports/latest-ai-summary")
async def get_latest_ai_summary():
    """Get the latest AI agent summary for programmatic access."""
    import json

    config = get_config()
    latest_file = Path(config.reports_directory) / "latest_ai_summary.json"

    if not latest_file.exists():
        return JSONResponse(content={"error": "No AI summary available"}, status_code=404)

    try:
        with open(latest_file) as f:
            summary = json.load(f)
        return summary
    except Exception as e:
        return JSONResponse(content={"error": f"Failed to load AI summary: {str(e)}"}, status_code=500)


@app.get("/run/test-monitoring")
async def run_test_monitoring(background_tasks: BackgroundTasks):
    """Run a simple test monitoring job that actually works."""
    import subprocess
    import uuid
    
    task_id = f"test_monitoring_{str(uuid.uuid4())[:8]}"
    
    def run_test_job():
        try:
            result = subprocess.run(
                ["python", "test_monitoring_job.py"],
                capture_output=True,
                text=True,
                timeout=60
            )
            print(f"Test monitoring job completed: {result.returncode}")
            print(f"Output: {result.stdout}")
            if result.stderr:
                print(f"Errors: {result.stderr}")
            return result.returncode == 0
        except Exception as e:
            print(f"Test monitoring job failed: {e}")
            return False
    
    background_tasks.add_task(run_test_job)
    return {
        "message": "Test monitoring job started",
        "task_id": task_id,
        "description": "Simple monitoring test with Telegram notification"
    }


@app.get("/health/docker")
async def check_docker_health():
    """Check if Docker is accessible for container monitoring."""
    try:
        from monitoring.log_collector.docker_logs import BashDockerLogCollector
        collector = BashDockerLogCollector()
        containers = collector.get_running_containers()

        return {
            "status": "healthy",
            "docker_accessible": True,
            "running_containers": len(containers),
            "container_names": containers
        }
    except Exception as e:
        return JSONResponse(
            content={
                "status": "unhealthy",
                "docker_accessible": False,
                "error": str(e)
            },
            status_code=503
        )


@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get status of a specific task."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    task_status = coordinator.get_task_status(task_id)
    if task_status is None:
        return JSONResponse(content={"error": "Task not found"}, status_code=404)

    return task_status


@app.post("/run/ai-monitoring")
async def trigger_ai_monitoring(background_tasks: BackgroundTasks):
    """Trigger the complete AI monitoring workflow."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)

    task_id = f"ai_monitoring_{int(asyncio.get_event_loop().time())}"

    async def run_ai_monitoring():
        ai_lead = AIMonitoringLead()
        await ai_lead.execute_daily_monitoring()

    background_tasks.add_task(run_ai_monitoring)

    return {
        "message": "AI monitoring workflow started",
        "task_id": task_id,
        "status": "started"
    }


@app.post("/run/autopar-monitoring")
@app.get("/run/autopar-monitoring")
async def trigger_autopar_monitoring(background_tasks: BackgroundTasks, hours: int = 4):
    """Trigger Autopar staging monitoring agent with comprehensive analysis."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)
    
    import subprocess
    import tempfile
    from datetime import datetime
    
    task_id = f"autopar_monitoring_{int(asyncio.get_event_loop().time())}"
    
    async def run_autopar_monitoring():
        """Execute the Autopar monitoring agent."""
        try:
            logger.info(f"🎯 Starting Autopar staging monitoring analysis (last {hours} hours)")
            
            # Run the autopar monitoring agent
            result = subprocess.run([
                'python', 'autopar_monitoring_agent.py', 
                '--hours', str(hours)
            ], 
            capture_output=True, 
            text=True, 
            timeout=7200  # 2 hour timeout
            )
            
            if result.returncode == 0:
                logger.info("✅ Autopar monitoring completed successfully")
                # Parse the output to extract status
                output_lines = result.stdout.strip().split('\n')
                status_line = next((line for line in output_lines if 'Status Determined:' in line), 'Status: COMPLETED')
                telegram_line = next((line for line in output_lines if 'Telegram' in line and 'sent' in line), 'Notification: Sent')
                
                return {
                    "status": "completed",
                    "autopar_analysis": status_line,
                    "telegram_notification": telegram_line,
                    "hours_analyzed": hours,
                    "environment": "autopar_staging",
                    "execution_time": "Completed within timeout"
                }
            else:
                logger.error(f"❌ Autopar monitoring failed: {result.stderr}")
                return {
                    "status": "failed", 
                    "error": result.stderr,
                    "hours_analyzed": hours,
                    "environment": "autopar_staging"
                }
                
        except subprocess.TimeoutExpired:
            logger.warning("⏱️ Autopar monitoring timed out after 2 hours")
            return {
                "status": "timeout",
                "message": "Autopar analysis took longer than 2 hours - this may be normal for comprehensive analysis",
                "hours_analyzed": hours,
                "environment": "autopar_staging"
            }
        except Exception as e:
            logger.error(f"💥 Autopar monitoring error: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "hours_analyzed": hours,
                "environment": "autopar_staging"
            }
    
    background_tasks.add_task(run_autopar_monitoring)
    
    return {
        "message": f"Autopar staging monitoring started - analyzing last {hours} hours",
        "task_id": task_id,
        "status": "started",
        "environment": "autopar_staging",
        "website": "staging.autopar.pitchai.net",
        "containers": ["autopar-redis", "autopar-rabbitmq"],
        "expected_duration": "Up to 2 hours",
        "telegram_notification": "Will be sent upon completion"
    }


@app.post("/run/claude-monitoring")
@app.get("/run/claude-monitoring")
async def trigger_claude_monitoring(background_tasks: BackgroundTasks, hours: int = 2):
    """Trigger Claude-powered monitoring agent with comprehensive analysis."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)
    
    import subprocess
    import tempfile
    from datetime import datetime
    
    task_id = f"claude_monitoring_{int(asyncio.get_event_loop().time())}"
    
    async def run_claude_monitoring():
        """Execute the Claude monitoring agent."""
        try:
            logger.info(f"🤖 Starting Claude monitoring analysis (last {hours} hours)")
            
            # Run the claude monitoring agent
            result = subprocess.run([
                'python', 'claude_monitoring_agent.py', 
                '--hours', str(hours)
            ], 
            capture_output=True, 
            text=True, 
            timeout=7200  # 2 hour timeout
            )
            
            if result.returncode == 0:
                logger.info("✅ Claude monitoring completed successfully")
                # Parse the output to extract status
                output_lines = result.stdout.strip().split('\n')
                status_line = next((line for line in output_lines if 'Status Determined:' in line), 'Status: COMPLETED')
                telegram_line = next((line for line in output_lines if 'Telegram' in line and 'sent' in line), 'Notification: Sent')
                
                return {
                    "status": "completed",
                    "claude_analysis": status_line,
                    "telegram_notification": telegram_line,
                    "hours_analyzed": hours,
                    "execution_time": "Completed within timeout"
                }
            else:
                logger.error(f"❌ Claude monitoring failed: {result.stderr}")
                return {
                    "status": "failed", 
                    "error": result.stderr,
                    "hours_analyzed": hours
                }
                
        except subprocess.TimeoutExpired:
            logger.warning("⏱️ Claude monitoring timed out after 2 hours")
            return {
                "status": "timeout",
                "message": "Claude analysis took longer than 2 hours - this may be normal for comprehensive analysis",
                "hours_analyzed": hours
            }
        except Exception as e:
            logger.error(f"💥 Claude monitoring error: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "hours_analyzed": hours
            }
    
    background_tasks.add_task(run_claude_monitoring)
    
    return {
        "message": f"Claude monitoring started - analyzing last {hours} hours",
        "task_id": task_id,
        "status": "started",
        "expected_duration": "Up to 2 hours",
        "telegram_notification": "Will be sent upon completion"
    }


@app.post("/run/quickchat-monitoring")
@app.get("/run/quickchat-monitoring")
async def trigger_quickchat_monitoring(background_tasks: BackgroundTasks, hours: int = 4):
    """Trigger Quickchat system monitoring agent with comprehensive analysis."""
    if not coordinator:
        return JSONResponse(content={"error": "System not initialized"}, status_code=503)
    
    import subprocess
    import tempfile
    from datetime import datetime
    
    task_id = f"quickchat_monitoring_{int(asyncio.get_event_loop().time())}"
    
    async def run_quickchat_monitoring():
        """Execute the Quickchat monitoring agent."""
        try:
            logger.info(f"💬 Starting Quickchat system monitoring analysis (last {hours} hours)")
            
            # Run the quickchat monitoring agent
            result = subprocess.run([
                'python', 'quickchat_monitoring_agent.py', 
                '--hours', str(hours)
            ], 
            capture_output=True, 
            text=True, 
            timeout=7200  # 2 hour timeout
            )
            
            if result.returncode == 0:
                logger.info("✅ Quickchat monitoring completed successfully")
                # Parse the output to extract status
                output_lines = result.stdout.strip().split('\n')
                status_line = next((line for line in output_lines if 'Status Determined:' in line), 'Status: COMPLETED')
                telegram_line = next((line for line in output_lines if 'Telegram' in line and 'sent' in line), 'Notification: Sent')
                
                return {
                    "status": "completed",
                    "quickchat_analysis": status_line,
                    "telegram_notification": telegram_line,
                    "hours_analyzed": hours,
                    "environment": "quickchat_system",
                    "execution_time": "Completed within timeout"
                }
            else:
                logger.error(f"❌ Quickchat monitoring failed: {result.stderr}")
                return {
                    "status": "failed", 
                    "error": result.stderr,
                    "hours_analyzed": hours,
                    "environment": "quickchat_system"
                }
                
        except subprocess.TimeoutExpired:
            logger.warning("⏱️ Quickchat monitoring timed out after 2 hours")
            return {
                "status": "timeout",
                "message": "Quickchat analysis took longer than 2 hours - this may be normal for comprehensive analysis",
                "hours_analyzed": hours,
                "environment": "quickchat_system"
            }
        except Exception as e:
            logger.error(f"💥 Quickchat monitoring error: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "hours_analyzed": hours,
                "environment": "quickchat_system"
            }
    
    background_tasks.add_task(run_quickchat_monitoring)
    
    return {
        "message": f"Quickchat system monitoring started - analyzing last {hours} hours",
        "task_id": task_id,
        "status": "started",
        "environment": "quickchat_system",
        "website": "chat.pitchai.net",
        "ui_tests": "Chat interaction functionality",
        "containers": ["chat-app", "chat-redis", "chat-postgres", "chat-nginx"],
        "expected_duration": "Up to 2 hours",
        "telegram_notification": "Will be sent upon completion"
    }


async def run_cli_command(command: str, *args):
    """Run monitoring system via CLI."""
    get_config()
    logger.info("Running CLI command", command=command, args=args)

    coordinator_instance = TaskCoordinator()
    await coordinator_instance.start()

    try:
        if command == "test":
            result = await coordinator_instance.run_ui_test_suite()
            print("UI Test Results:")
            print(f"Total: {result.get('test_count', 0)}")
            print(f"Passed: {result.get('passed', 0)}")
            print(f"Failed: {result.get('failed', 0)}")

        elif command == "logs":
            hours_back = int(args[0]) if args else 1
            result = await coordinator_instance.collect_container_logs(hours_back)
            print("Log Collection Results:")
            print(f"Containers: {result.get('containers_checked', 0)}")
            print(f"Total logs: {result.get('total_logs', 0)}")
            print(f"Errors found: {result.get('errors_found', 0)}")

        elif command == "report":
            result = await coordinator_instance.generate_daily_report()
            print("Daily Report Generated:")
            print(f"Test runs analyzed: {result.get('test_runs_analyzed', 0)}")
            print(f"Issues found: {result.get('issues_found', 0)}")

        elif command == "status":
            status = coordinator_instance.get_system_status()
            print("System Status:")
            print(f"Running tasks: {status['running_tasks']}")
            print(f"Completed tasks: {status['completed_tasks']}")
            print(f"Scheduler running: {status['scheduler']['running']}")

        elif command == "ai":
            print("🤖 Running AI Monitoring Lead workflow...")
            ai_lead = AIMonitoringLead()
            result = await ai_lead.execute_daily_monitoring()
            print("AI Monitoring Results:")
            print(f"Health Status: {result.get('summary', {}).get('health_status', 'unknown')}")
            print(f"Health Score: {result.get('summary', {}).get('health_score', 0):.1f}/100")
            print(f"UI Tests: {result.get('summary', {}).get('ui_tests_passed', 0)}/{result.get('summary', {}).get('ui_tests_total', 0)} passed")
            print(f"Containers: {result.get('summary', {}).get('containers_monitored', 0)} monitored")
            print(f"Incidents: {result.get('summary', {}).get('incidents_created', 0)} created")
            print(f"Notification sent: {result.get('notification_sent', False)}")

        else:
            print(f"Unknown command: {command}")
            print("Available commands: test, logs [hours], report, status, ai")

    finally:
        await coordinator_instance.stop()


def main():
    """Main entry point with argument handling."""
    if len(sys.argv) < 2:
        # No arguments - start web server
        get_config()
        logger.info("Starting monitoring web server")
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level="info"
        )
    else:
        # CLI mode
        command = sys.argv[1]
        args = sys.argv[2:]
        asyncio.run(run_cli_command(command, *args))


if __name__ == "__main__":
    main()
