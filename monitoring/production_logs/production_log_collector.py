"""Production Log Collector - Safe, Non-Invasive Production Log Access

This module provides a safe interface for collecting logs from production Docker
containers without any destructive operations. All commands are READ-ONLY.

SAFETY FEATURES:
- Only READ-ONLY Docker operations allowed
- Explicit blocking of all destructive commands 
- SSH-based secure remote access
- Comprehensive error handling and logging
- No modifications to running containers
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import structlog
from pathlib import Path

from ..remote_logs.ssh_log_collector import RemoteLogCollector, create_afas_log_collector

logger = structlog.get_logger(__name__)


class ProductionLogCollector:
    """Safe production log collector with read-only access to Docker containers.
    
    This class provides a clean interface for accessing production logs while
    maintaining strict safety guarantees:
    - Only READ-ONLY operations
    - No container modifications
    - Comprehensive safety checks
    - Structured log output
    """
    
    def __init__(self):
        """Initialize production log collector.
        
        Automatically loads .env file and uses environment variables for SSH configuration:
        - HETZNER_HOST: Production server hostname
        - HETZNER_USER: SSH username
        - HETZNER_SSH_KEY: SSH private key
        """
        self._load_env_file()
        self._validate_environment()
        logger.info("Production log collector initialized safely")
    
    def _load_env_file(self) -> None:
        """Load environment variables from .env file if it exists."""
        # Look for .env file in current directory and parent directories
        current_dir = Path.cwd()
        env_file = None
        
        # Check current directory and up to 3 parent directories
        for path in [current_dir] + list(current_dir.parents)[:3]:
            potential_env = path / '.env'
            if potential_env.exists():
                env_file = potential_env
                break
        
        if env_file:
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            # Remove quotes if present
                            value = value.strip('"\'')
                            # Only set if not already in environment
                            if key not in os.environ:
                                os.environ[key] = value
                
                logger.info("Loaded environment variables from .env file", 
                           env_file=str(env_file))
            except Exception as e:
                logger.warning("Failed to load .env file", 
                              env_file=str(env_file), error=str(e))
        else:
            logger.debug("No .env file found in current or parent directories")
    
    def _validate_environment(self) -> None:
        """Validate required environment variables are present."""
        required_vars = ['HETZNER_HOST', 'HETZNER_USER', 'HETZNER_SSH_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        logger.info("Environment variables validated", 
                   host=os.getenv('HETZNER_HOST'),
                   user=os.getenv('HETZNER_USER'))
    
    def get_container_list(self) -> List[Dict[str, str]]:
        """Get list of running containers on production server.
        
        Returns:
            List of container information dictionaries with keys:
            - id: Container ID
            - name: Container name
            - image: Docker image
            - status: Container status
            - ports: Exposed ports
            - created: Creation timestamp
        """
        logger.info("Fetching production container list")
        
        try:
            with create_afas_log_collector() as collector:
                containers = collector.get_running_containers()
                
            logger.info("Retrieved container list", count=len(containers))
            return containers
            
        except Exception as e:
            logger.error("Failed to get container list", error=str(e))
            raise RuntimeError(f"Container list retrieval failed: {str(e)}")
    
    def get_logs_from_container(
        self, 
        container_name: str, 
        hours_back: int = 1
    ) -> List[Dict[str, Any]]:
        """Get logs from a specific container.
        
        Args:
            container_name: Name or ID of the container
            hours_back: Hours of logs to retrieve (default: 1)
            
        Returns:
            List of log entries with structured format:
            - container_name: Container name
            - timestamp: ISO timestamp
            - level: Log level (INFO, ERROR, WARNING, DEBUG)
            - message: Log message
            - raw_line: Original log line
        """
        logger.info("Collecting logs from container", 
                   container=container_name, hours_back=hours_back)
        
        try:
            with create_afas_log_collector() as collector:
                logs = collector.get_container_logs(container_name, hours_back)
                
            logger.info("Retrieved container logs", 
                       container=container_name, entries=len(logs))
            return logs
            
        except Exception as e:
            logger.error("Failed to get container logs", 
                        container=container_name, error=str(e))
            raise RuntimeError(f"Log retrieval failed for {container_name}: {str(e)}")
    
    def get_logs_from_all_containers(
        self, 
        hours_back: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get logs from all running containers.
        
        Args:
            hours_back: Hours of logs to retrieve (default: 1)
            
        Returns:
            Dictionary mapping container names to their log entries
        """
        logger.info("Collecting logs from all containers", hours_back=hours_back)
        
        try:
            with create_afas_log_collector() as collector:
                all_logs = collector.get_all_container_logs(hours_back)
                
            total_entries = sum(len(logs) for logs in all_logs.values())
            logger.info("Retrieved all container logs", 
                       containers=len(all_logs), total_entries=total_entries)
            return all_logs
            
        except Exception as e:
            logger.error("Failed to get all container logs", error=str(e))
            raise RuntimeError(f"Bulk log retrieval failed: {str(e)}")
    
    def get_error_logs_only(
        self, 
        hours_back: int = 1
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get only error-level logs from all containers.
        
        Args:
            hours_back: Hours of logs to analyze (default: 1)
            
        Returns:
            Dictionary mapping container names to their error log entries
        """
        logger.info("Collecting error logs only", hours_back=hours_back)
        
        all_logs = self.get_logs_from_all_containers(hours_back)
        
        error_logs = {}
        for container_name, logs in all_logs.items():
            container_errors = [log for log in logs if log.get('level') == 'ERROR']
            if container_errors:
                error_logs[container_name] = container_errors
        
        total_errors = sum(len(errors) for errors in error_logs.values())
        logger.info("Filtered error logs", 
                   containers_with_errors=len(error_logs), 
                   total_errors=total_errors)
        
        return error_logs
    
    def get_error_summary(self, hours_back: int = 1) -> Dict[str, Any]:
        """Get comprehensive error summary for production monitoring.
        
        Args:
            hours_back: Hours to analyze (default: 1)
            
        Returns:
            Structured error summary with:
            - timestamp: Analysis timestamp
            - analysis_period_hours: Period analyzed
            - total_containers: Total containers checked
            - containers_with_errors: Count of containers with errors
            - total_error_entries: Total error log entries
            - error_breakdown: Per-container error details
            - critical_issues: High-priority issues detected
        """
        logger.info("Generating error summary", hours_back=hours_back)
        
        try:
            with create_afas_log_collector() as collector:
                summary = collector.get_error_summary(hours_back)
                
            logger.info("Generated error summary", 
                       total_errors=summary['total_error_entries'],
                       containers_with_errors=summary['containers_with_errors'])
            return summary
            
        except Exception as e:
            logger.error("Failed to generate error summary", error=str(e))
            raise RuntimeError(f"Error summary generation failed: {str(e)}")
    
    def save_logs_to_file(
        self, 
        logs: Dict[str, List[Dict[str, Any]]], 
        filename: Optional[str] = None
    ) -> str:
        """Save collected logs to a JSON file.
        
        Args:
            logs: Log data to save
            filename: Optional filename (auto-generated if not provided)
            
        Returns:
            Path to the saved file
        """
        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"production_logs_{timestamp}.json"
        
        # Ensure logs directory exists
        logs_dir = "logs"
        os.makedirs(logs_dir, exist_ok=True)
        
        filepath = os.path.join(logs_dir, filename)
        
        # Prepare data for JSON serialization
        serializable_logs = {
            "timestamp": datetime.utcnow().isoformat(),
            "collection_source": "production_ssh",
            "containers": logs
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(serializable_logs, f, indent=2, default=str)
            
            logger.info("Saved logs to file", filepath=filepath, 
                       containers=len(logs))
            return filepath
            
        except Exception as e:
            logger.error("Failed to save logs", filepath=filepath, error=str(e))
            raise RuntimeError(f"Log file save failed: {str(e)}")
    
    def health_check(self) -> Dict[str, Any]:
        """Perform a health check of the production log collection system.
        
        Returns:
            Health check results with connection and access status
        """
        logger.info("Performing production log collector health check")
        
        health_status = {
            "timestamp": datetime.utcnow().isoformat(),
            "environment_variables": False,
            "ssh_connection": False,
            "docker_access": False,
            "container_count": 0,
            "status": "unhealthy",
            "errors": []
        }
        
        try:
            # Check environment variables
            self._validate_environment()
            health_status["environment_variables"] = True
            
            # Test SSH connection and Docker access
            with create_afas_log_collector() as collector:
                health_status["ssh_connection"] = True
                
                # Test Docker access by listing containers
                containers = collector.get_running_containers()
                health_status["docker_access"] = True
                health_status["container_count"] = len(containers)
            
            health_status["status"] = "healthy"
            logger.info("Health check passed", container_count=health_status["container_count"])
            
        except Exception as e:
            error_msg = str(e)
            health_status["errors"].append(error_msg)
            logger.error("Health check failed", error=error_msg)
        
        return health_status