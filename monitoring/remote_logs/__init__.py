"""Remote log collection module for production AFAS containers.

This module provides secure, read-only access to Docker container logs
on remote servers using SSH. All operations are non-invasive and safe.
"""

from .ssh_log_collector import RemoteLogCollector

__all__ = ["RemoteLogCollector"]
