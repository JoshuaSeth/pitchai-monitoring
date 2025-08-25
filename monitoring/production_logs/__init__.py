"""Production Log Collection Module

A safe, non-invasive module for collecting logs from production Docker containers
via SSH. This module provides a clean interface for read-only log access without
affecting running containers.

All operations are strictly READ-ONLY and non-destructive.
"""

from .log_interface import LogInterface
from .production_log_collector import ProductionLogCollector

__all__ = ['ProductionLogCollector', 'LogInterface']
