"""Daily orchestrator for automated monitoring execution."""

import asyncio
import os
from datetime import datetime

import structlog

from .monitoring_lead import AIMonitoringLead

logger = structlog.get_logger(__name__)


class DailyOrchestrator:
    """Orchestrates daily monitoring tasks for containerized deployment."""

    def __init__(self):
        """Initialize the daily orchestrator."""
        self.monitoring_lead = AIMonitoringLead()
        logger.info("Daily orchestrator initialized")

    async def run_daily_monitoring(self) -> None:
        """Execute daily monitoring workflow.

        This is designed to be called by cron or scheduler within the container.
        """
        logger.info("Starting daily monitoring orchestration",
                   timestamp=datetime.utcnow().isoformat(),
                   container_id=os.getenv("HOSTNAME", "unknown"))

        try:
            # Execute the monitoring workflow
            report = await self.monitoring_lead.execute_daily_monitoring()

            # Log completion
            logger.info("Daily monitoring completed successfully",
                       health_status=report.get("summary", {}).get("health_status"),
                       health_score=report.get("summary", {}).get("health_score"),
                       incidents=len(report.get("incidents", [])))

        except Exception as e:
            logger.error("Daily monitoring orchestration failed", error=str(e))
            raise

    @classmethod
    def run(cls):
        """Class method to run the orchestrator (for cron/scripts)."""
        orchestrator = cls()
        asyncio.run(orchestrator.run_daily_monitoring())


# Script entry point for containerized execution
if __name__ == "__main__":
    # Setup logging for container environment
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run the daily monitoring
    DailyOrchestrator.run()
