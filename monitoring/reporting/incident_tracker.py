"""Incident tracking and management for monitoring system."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import structlog

from ..config import get_config


logger = structlog.get_logger(__name__)


class Incident:
    """Represents a monitoring incident."""
    
    def __init__(
        self,
        incident_id: str,
        test_name: str,
        failure_time: datetime,
        error_message: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        status: str = "open"
    ):
        self.incident_id = incident_id
        self.test_name = test_name
        self.failure_time = failure_time
        self.error_message = error_message
        self.screenshot_path = screenshot_path
        self.status = status
        self.creation_time = datetime.utcnow()
        self.updates: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}
    
    def add_update(self, update_type: str, message: str, author: Optional[str] = None):
        """Add an update to the incident."""
        update = {
            "timestamp": datetime.utcnow().isoformat(),
            "type": update_type,
            "message": message,
            "author": author
        }
        self.updates.append(update)
        logger.info("Added incident update", 
                   incident_id=self.incident_id, 
                   update_type=update_type)
    
    def set_status(self, status: str, author: Optional[str] = None):
        """Update incident status."""
        old_status = self.status
        self.status = status
        self.add_update("status_change", f"Status changed from {old_status} to {status}", author)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert incident to dictionary."""
        return {
            "incident_id": self.incident_id,
            "test_name": self.test_name,
            "failure_time": self.failure_time.isoformat(),
            "creation_time": self.creation_time.isoformat(),
            "error_message": self.error_message,
            "screenshot_path": self.screenshot_path,
            "status": self.status,
            "updates": self.updates,
            "metadata": self.metadata
        }


class IncidentTracker:
    """Tracks and manages monitoring incidents."""
    
    def __init__(self):
        self.config = get_config()
        self.incidents_dir = Path(self.config.incidents_directory)
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        
        # Status definitions
        self.valid_statuses = [
            "open",
            "investigating", 
            "identified",
            "fixed",
            "verified",
            "closed",
            "false_positive"
        ]
    
    def create_incident(
        self,
        test_name: str,
        failure_time: datetime,
        error_message: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        incident_id: Optional[str] = None
    ) -> Incident:
        """Create a new incident."""
        if incident_id is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_test_name = test_name.replace(" ", "_").replace("—", "_").lower()
            incident_id = f"{safe_test_name}_{timestamp}"
        
        incident = Incident(
            incident_id=incident_id,
            test_name=test_name,
            failure_time=failure_time,
            error_message=error_message,
            screenshot_path=screenshot_path
        )
        
        # Save incident
        self.save_incident(incident)
        
        logger.info("Created new incident", 
                   incident_id=incident_id,
                   test_name=test_name)
        
        return incident
    
    def save_incident(self, incident: Incident):
        """Save incident to file."""
        incident_path = self.incidents_dir / f"{incident.incident_id}.json"
        
        with open(incident_path, 'w') as f:
            json.dump(incident.to_dict(), f, indent=2, default=str)
        
        logger.debug("Saved incident", incident_id=incident.incident_id)
    
    def load_incident(self, incident_id: str) -> Optional[Incident]:
        """Load an incident from file."""
        incident_path = self.incidents_dir / f"{incident_id}.json"
        
        if not incident_path.exists():
            logger.warning("Incident file not found", incident_id=incident_id)
            return None
        
        with open(incident_path, 'r') as f:
            data = json.load(f)
        
        incident = Incident(
            incident_id=data["incident_id"],
            test_name=data["test_name"],
            failure_time=datetime.fromisoformat(data["failure_time"]),
            error_message=data.get("error_message"),
            screenshot_path=data.get("screenshot_path"),
            status=data.get("status", "open")
        )
        
        incident.creation_time = datetime.fromisoformat(data["creation_time"])
        incident.updates = data.get("updates", [])
        incident.metadata = data.get("metadata", {})
        
        logger.debug("Loaded incident", incident_id=incident_id)
        return incident
    
    def list_incidents(
        self,
        status: Optional[str] = None,
        test_name: Optional[str] = None,
        days_back: Optional[int] = None
    ) -> List[Incident]:
        """List incidents with optional filtering."""
        incidents = []
        
        for incident_file in self.incidents_dir.glob("*.json"):
            try:
                incident = self.load_incident(incident_file.stem)
                if incident is None:
                    continue
                
                # Apply filters
                if status and incident.status != status:
                    continue
                
                if test_name and incident.test_name != test_name:
                    continue
                
                if days_back:
                    cutoff_date = datetime.utcnow() - timedelta(days=days_back)
                    if incident.creation_time < cutoff_date:
                        continue
                
                incidents.append(incident)
                
            except Exception as e:
                logger.error("Failed to load incident", file=incident_file.name, error=str(e))
        
        # Sort by creation time (newest first)
        incidents.sort(key=lambda x: x.creation_time, reverse=True)
        
        logger.info("Listed incidents", count=len(incidents), filters={
            "status": status,
            "test_name": test_name,
            "days_back": days_back
        })
        
        return incidents
    
    def update_incident(
        self,
        incident_id: str,
        update_type: str,
        message: str,
        author: Optional[str] = None,
        new_status: Optional[str] = None
    ) -> bool:
        """Update an existing incident."""
        incident = self.load_incident(incident_id)
        if incident is None:
            logger.error("Cannot update non-existent incident", incident_id=incident_id)
            return False
        
        # Add update
        incident.add_update(update_type, message, author)
        
        # Change status if requested
        if new_status:
            if new_status not in self.valid_statuses:
                logger.error("Invalid status", status=new_status, valid_statuses=self.valid_statuses)
                return False
            incident.set_status(new_status, author)
        
        # Save updated incident
        self.save_incident(incident)
        
        logger.info("Updated incident", 
                   incident_id=incident_id,
                   update_type=update_type,
                   new_status=new_status)
        
        return True
    
    def get_incident_statistics(self, days_back: int = 30) -> Dict[str, Any]:
        """Get statistics about incidents over a time period."""
        incidents = self.list_incidents(days_back=days_back)
        
        # Group by status
        status_counts = {}
        for incident in incidents:
            status_counts[incident.status] = status_counts.get(incident.status, 0) + 1
        
        # Group by test name
        test_counts = {}
        for incident in incidents:
            test_counts[incident.test_name] = test_counts.get(incident.test_name, 0) + 1
        
        # Calculate resolution times for closed incidents
        resolution_times = []
        for incident in incidents:
            if incident.status in ["closed", "verified", "false_positive"]:
                resolution_time = (incident.creation_time - incident.failure_time).total_seconds() / 3600  # hours
                resolution_times.append(resolution_time)
        
        avg_resolution_time = sum(resolution_times) / len(resolution_times) if resolution_times else 0
        
        statistics = {
            "period_days": days_back,
            "total_incidents": len(incidents),
            "status_breakdown": status_counts,
            "test_breakdown": test_counts,
            "most_problematic_test": max(test_counts.keys(), key=lambda k: test_counts[k]) if test_counts else None,
            "resolution_statistics": {
                "avg_resolution_time_hours": avg_resolution_time,
                "resolved_incidents": len(resolution_times),
                "open_incidents": status_counts.get("open", 0) + status_counts.get("investigating", 0)
            }
        }
        
        logger.info("Generated incident statistics", 
                   total_incidents=len(incidents),
                   open_incidents=statistics["resolution_statistics"]["open_incidents"])
        
        return statistics
    
    def generate_incident_summary(self, incident_id: str) -> Dict[str, Any]:
        """Generate a summary for team lead consumption."""
        incident = self.load_incident(incident_id)
        if incident is None:
            return {"error": "Incident not found"}
        
        # Create team lead friendly summary
        summary = {
            "incident_id": incident.incident_id,
            "test_name": incident.test_name,
            "failure_time": incident.failure_time.strftime("%Y-%m-%d %H:%M UTC"),
            "status": incident.status,
            "error_summary": incident.error_message[:200] + "..." if incident.error_message and len(incident.error_message) > 200 else incident.error_message,
            "screenshot_available": incident.screenshot_path is not None,
            "age_hours": (datetime.utcnow() - incident.creation_time).total_seconds() / 3600,
            "update_count": len(incident.updates),
            "latest_update": incident.updates[-1] if incident.updates else None,
            "needs_attention": incident.status in ["open", "investigating"] and (datetime.utcnow() - incident.creation_time).total_seconds() > 3600  # older than 1 hour
        }
        
        return summary