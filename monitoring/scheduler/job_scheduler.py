"""Job scheduling for automated monitoring tasks."""

import asyncio
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_config


logger = structlog.get_logger(__name__)


class JobScheduler:
    """Manages scheduled monitoring jobs using APScheduler."""
    
    def __init__(self):
        self.config = get_config()
        self.scheduler = AsyncIOScheduler()
        self.jobs: Dict[str, Any] = {}
        self.running = False
    
    async def start(self):
        """Start the job scheduler."""
        if self.running:
            logger.warning("Scheduler already running")
            return
        
        self.scheduler.start()
        self.running = True
        logger.info("Job scheduler started")
    
    async def stop(self):
        """Stop the job scheduler."""
        if not self.running:
            return
        
        self.scheduler.shutdown(wait=True)
        self.running = False
        logger.info("Job scheduler stopped")
    
    def add_cron_job(
        self,
        job_id: str,
        func: Callable,
        cron_expression: str,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None
    ):
        """Add a cron-scheduled job."""
        if job_id in self.jobs:
            logger.warning("Job already exists, replacing", job_id=job_id)
            self.remove_job(job_id)
        
        # Parse cron expression (format: "minute hour day month day_of_week")
        cron_parts = cron_expression.split()
        if len(cron_parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expression}")
        
        trigger = CronTrigger(
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4]
        )
        
        job = self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or (),
            kwargs=kwargs or {},
            name=description or job_id
        )
        
        self.jobs[job_id] = {
            "job": job,
            "type": "cron",
            "expression": cron_expression,
            "description": description,
            "added_at": datetime.utcnow()
        }
        
        logger.info("Added cron job", 
                   job_id=job_id,
                   cron=cron_expression,
                   description=description)
    
    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int,
        args: Optional[tuple] = None,
        kwargs: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None
    ):
        """Add an interval-based job."""
        if job_id in self.jobs:
            logger.warning("Job already exists, replacing", job_id=job_id)
            self.remove_job(job_id)
        
        trigger = IntervalTrigger(seconds=seconds)
        
        job = self.scheduler.add_job(
            func=func,
            trigger=trigger,
            id=job_id,
            args=args or (),
            kwargs=kwargs or {},
            name=description or job_id
        )
        
        self.jobs[job_id] = {
            "job": job,
            "type": "interval",
            "seconds": seconds,
            "description": description,
            "added_at": datetime.utcnow()
        }
        
        logger.info("Added interval job", 
                   job_id=job_id,
                   interval_seconds=seconds,
                   description=description)
    
    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        if job_id not in self.jobs:
            logger.warning("Job not found", job_id=job_id)
            return False
        
        try:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
            logger.info("Removed job", job_id=job_id)
            return True
        except Exception as e:
            logger.error("Failed to remove job", job_id=job_id, error=str(e))
            return False
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        if job_id not in self.jobs:
            logger.warning("Job not found", job_id=job_id)
            return False
        
        try:
            self.scheduler.pause_job(job_id)
            logger.info("Paused job", job_id=job_id)
            return True
        except Exception as e:
            logger.error("Failed to pause job", job_id=job_id, error=str(e))
            return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        if job_id not in self.jobs:
            logger.warning("Job not found", job_id=job_id)
            return False
        
        try:
            self.scheduler.resume_job(job_id)
            logger.info("Resumed job", job_id=job_id)
            return True
        except Exception as e:
            logger.error("Failed to resume job", job_id=job_id, error=str(e))
            return False
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status information for a job."""
        if job_id not in self.jobs:
            return None
        
        job_info = self.jobs[job_id]
        scheduler_job = self.scheduler.get_job(job_id)
        
        if scheduler_job is None:
            return None
        
        return {
            "job_id": job_id,
            "name": scheduler_job.name,
            "type": job_info["type"],
            "next_run": scheduler_job.next_run_time.isoformat() if scheduler_job.next_run_time else None,
            "added_at": job_info["added_at"].isoformat(),
            "description": job_info.get("description"),
            "paused": scheduler_job.next_run_time is None
        }
    
    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all scheduled jobs."""
        job_statuses = []
        for job_id in self.jobs:
            status = self.get_job_status(job_id)
            if status:
                job_statuses.append(status)
        
        return job_statuses
    
    def get_scheduler_status(self) -> Dict[str, Any]:
        """Get overall scheduler status."""
        return {
            "running": self.running,
            "job_count": len(self.jobs),
            "next_run": min(
                (job.next_run_time for job in self.scheduler.get_jobs() if job.next_run_time),
                default=None
            )
        }
    
    async def run_job_once(self, job_id: str) -> bool:
        """Run a scheduled job immediately (one-time execution)."""
        if job_id not in self.jobs:
            logger.warning("Job not found", job_id=job_id)
            return False
        
        try:
            scheduler_job = self.scheduler.get_job(job_id)
            if scheduler_job is None:
                logger.error("Scheduler job not found", job_id=job_id)
                return False
            
            # Execute the job function
            if asyncio.iscoroutinefunction(scheduler_job.func):
                await scheduler_job.func(*scheduler_job.args, **scheduler_job.kwargs)
            else:
                scheduler_job.func(*scheduler_job.args, **scheduler_job.kwargs)
            
            logger.info("Executed job manually", job_id=job_id)
            return True
            
        except Exception as e:
            logger.error("Failed to execute job", job_id=job_id, error=str(e))
            return False