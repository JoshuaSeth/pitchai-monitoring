"""Reporting module for test results and incident tracking."""

from .incident_tracker import IncidentTracker
from .report_generator import ReportGenerator

__all__ = ["ReportGenerator", "IncidentTracker"]
