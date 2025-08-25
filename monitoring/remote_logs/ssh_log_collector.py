"""Secure SSH-based log collection from remote AFAS production containers.

This module implements SAFE, READ-ONLY log collection from Docker containers
running on remote servers. No destructive operations are performed.
"""

import os
import json
import tempfile
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import structlog
import paramiko
from io import StringIO

logger = structlog.get_logger(__name__)

# SAFE Docker commands - READ-ONLY operations only
SAFE_DOCKER_COMMANDS = {
    'list_containers': 'docker ps --format json --no-trunc',
    'get_logs': 'docker logs --timestamps --tail {tail}',
    'get_logs_since': 'docker logs --timestamps --since {since}',
    'inspect_container': 'docker inspect',
    'get_stats': 'docker stats --no-stream --format json'
}


class RemoteLogCollector:
    """Secure remote log collection for AFAS production containers.
    
    This class implements SAFE, READ-ONLY operations to collect logs from
    Docker containers on remote servers. No invasive or destructive operations
    are performed.
    """
    
    def __init__(self, host: str, username: str, ssh_key: str, port: int = 22):
        """Initialize remote log collector.
        
        Args:
            host: Remote server hostname/IP
            username: SSH username
            ssh_key: SSH private key content
            port: SSH port (default: 22)
        """
        self.host = host
        self.username = username
        self.ssh_key = ssh_key
        self.port = port
        self.ssh_client = None
        
        logger.info("Remote log collector initialized", 
                   host=host, username=username, port=port)
    
    def __enter__(self):
        """Context manager entry - establish SSH connection."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close SSH connection."""
        self.disconnect()
    
    def connect(self) -> None:
        """Establish secure SSH connection to remote server."""
        try:
            # Create SSH client
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Parse SSH key
            key_file = StringIO(self.ssh_key.replace('\\n', '\n'))
            private_key = paramiko.Ed25519Key.from_private_key(key_file)
            
            # Connect to remote server
            logger.info("Connecting to remote server", host=self.host)
            self.ssh_client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                pkey=private_key,
                timeout=30
            )
            
            logger.info("Successfully connected to remote server")
            
        except Exception as e:
            logger.error("Failed to connect to remote server", error=str(e))
            if self.ssh_client:
                self.ssh_client.close()
            raise
    
    def disconnect(self) -> None:
        """Close SSH connection."""
        if self.ssh_client:
            self.ssh_client.close()
            logger.info("Disconnected from remote server")
    
    def _execute_safe_command(self, command: str) -> tuple[str, str, int]:
        """Execute a SAFE, READ-ONLY command on remote server.
        
        Args:
            command: Safe command to execute
            
        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        if not self.ssh_client:
            raise RuntimeError("Not connected to remote server")
        
        # Security check: ensure only safe commands are executed
        if not self._is_safe_command(command):
            raise ValueError(f"Unsafe command blocked: {command}")
        
        logger.debug("Executing safe command", command=command)
        
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command, timeout=60)
            
            stdout_content = stdout.read().decode('utf-8')
            stderr_content = stderr.read().decode('utf-8')
            exit_code = stdout.channel.recv_exit_status()
            
            return stdout_content, stderr_content, exit_code
            
        except Exception as e:
            logger.error("Command execution failed", command=command, error=str(e))
            raise
    
    def _is_safe_command(self, command: str) -> bool:
        """Verify that a command is safe and read-only.
        
        Args:
            command: Command to check
            
        Returns:
            True if command is safe
        """
        # List of safe Docker operations (READ-ONLY)
        safe_operations = [
            'docker ps',
            'docker logs',
            'docker inspect',
            'docker stats --no-stream',
            'docker version',
            'docker info'
        ]
        
        # List of FORBIDDEN operations
        forbidden_operations = [
            'docker exec',
            'docker run',
            'docker start',
            'docker stop',
            'docker restart',
            'docker kill',
            'docker rm',
            'docker rmi',
            'docker commit',
            'docker build',
            'docker push',
            'docker pull',
            'docker attach',
            'docker cp',
            'docker create',
            'docker update'
        ]
        
        # Check for forbidden operations
        for forbidden in forbidden_operations:
            if forbidden in command.lower():
                logger.error("BLOCKED: Forbidden operation detected", 
                           command=command, forbidden_op=forbidden)
                return False
        
        # Check for safe operations
        for safe_op in safe_operations:
            if command.strip().startswith(safe_op):
                return True
        
        logger.warning("Command not in safe operations list", command=command)
        return False
    
    def get_running_containers(self) -> List[Dict[str, Any]]:
        """Get list of running Docker containers (READ-ONLY).
        
        Returns:
            List of container information dictionaries
        """
        logger.info("Fetching running containers list")
        
        command = SAFE_DOCKER_COMMANDS['list_containers']
        stdout, stderr, exit_code = self._execute_safe_command(command)
        
        if exit_code != 0:
            logger.error("Failed to list containers", stderr=stderr)
            return []
        
        containers = []
        for line in stdout.strip().split('\n'):
            if line.strip():
                try:
                    container_info = json.loads(line)
                    containers.append({
                        'id': container_info.get('ID', ''),
                        'name': container_info.get('Names', ''),
                        'image': container_info.get('Image', ''),
                        'status': container_info.get('Status', ''),
                        'ports': container_info.get('Ports', ''),
                        'created': container_info.get('CreatedAt', ''),
                        'command': container_info.get('Command', '')
                    })
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse container info", line=line, error=str(e))
        
        logger.info("Found running containers", count=len(containers))
        return containers
    
    def get_container_logs(
        self, 
        container_name: str, 
        hours_back: int = 1,
        tail_lines: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get logs from a specific container (READ-ONLY).
        
        Args:
            container_name: Name or ID of container
            hours_back: Hours of logs to collect
            tail_lines: Maximum number of lines to retrieve
            
        Returns:
            List of log entries
        """
        logger.info("Collecting logs", container=container_name, hours_back=hours_back)
        
        # Calculate since time
        since_time = datetime.utcnow() - timedelta(hours=hours_back)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S.000000000Z')
        
        # Use safe log collection command
        command = f"{SAFE_DOCKER_COMMANDS['get_logs_since'].format(since=since_str)} {container_name}"
        stdout, stderr, exit_code = self._execute_safe_command(command)
        
        if exit_code != 0:
            logger.error("Failed to get container logs", 
                        container=container_name, stderr=stderr)
            return []
        
        # Parse logs
        log_entries = []
        for line in stdout.strip().split('\n'):
            if line.strip():
                entry = self._parse_log_line(container_name, line)
                if entry:
                    log_entries.append(entry)
        
        logger.info("Collected logs", container=container_name, entries=len(log_entries))
        return log_entries
    
    def _parse_log_line(self, container_name: str, line: str) -> Optional[Dict[str, Any]]:
        """Parse a single log line into structured format.
        
        Args:
            container_name: Name of the container
            line: Raw log line
            
        Returns:
            Parsed log entry or None if parsing fails
        """
        try:
            # Docker logs format: timestamp message
            parts = line.split(' ', 1)
            if len(parts) < 2:
                return None
            
            timestamp_str = parts[0]
            message = parts[1]
            
            # Parse timestamp
            try:
                if timestamp_str.endswith('Z'):
                    # Remove nanoseconds for parsing
                    base_time = timestamp_str.split('.')[0] if '.' in timestamp_str else timestamp_str[:-1]
                    timestamp = datetime.fromisoformat(base_time)
                else:
                    timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                timestamp = datetime.utcnow()
            
            # Detect log level
            level = 'INFO'
            message_upper = message.upper()
            if any(keyword in message_upper for keyword in ['ERROR', 'FATAL', 'EXCEPTION']):
                level = 'ERROR'
            elif any(keyword in message_upper for keyword in ['WARNING', 'WARN']):
                level = 'WARNING'
            elif any(keyword in message_upper for keyword in ['DEBUG']):
                level = 'DEBUG'
            
            return {
                'container_name': container_name,
                'timestamp': timestamp.isoformat(),
                'level': level,
                'message': message.strip(),
                'raw_line': line
            }
            
        except Exception as e:
            logger.debug("Failed to parse log line", line=line, error=str(e))
            return None
    
    def get_all_container_logs(self, hours_back: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        """Get logs from all running containers (READ-ONLY).
        
        Args:
            hours_back: Hours of logs to collect
            
        Returns:
            Dictionary mapping container names to their log entries
        """
        logger.info("Collecting logs from all containers", hours_back=hours_back)
        
        # Get running containers
        containers = self.get_running_containers()
        
        all_logs = {}
        for container in containers:
            container_name = container['name']
            try:
                logs = self.get_container_logs(container_name, hours_back)
                all_logs[container_name] = logs
            except Exception as e:
                logger.error("Failed to collect logs", 
                           container=container_name, error=str(e))
                all_logs[container_name] = []
        
        total_entries = sum(len(logs) for logs in all_logs.values())
        logger.info("Collected all container logs", 
                   containers=len(all_logs), total_entries=total_entries)
        
        return all_logs
    
    def get_error_summary(self, hours_back: int = 1) -> Dict[str, Any]:
        """Get summary of errors across all containers (READ-ONLY).
        
        Args:
            hours_back: Hours to analyze
            
        Returns:
            Error summary report
        """
        logger.info("Generating error summary", hours_back=hours_back)
        
        all_logs = self.get_all_container_logs(hours_back)
        
        summary = {
            'timestamp': datetime.utcnow().isoformat(),
            'analysis_period_hours': hours_back,
            'total_containers': len(all_logs),
            'containers_with_errors': 0,
            'total_error_entries': 0,
            'error_breakdown': {},
            'critical_issues': []
        }
        
        for container_name, logs in all_logs.items():
            error_logs = [log for log in logs if log['level'] == 'ERROR']
            
            if error_logs:
                summary['containers_with_errors'] += 1
                summary['total_error_entries'] += len(error_logs)
                
                summary['error_breakdown'][container_name] = {
                    'error_count': len(error_logs),
                    'recent_errors': [
                        {
                            'timestamp': log['timestamp'],
                            'message': log['message'][:200]
                        }
                        for log in error_logs[-5:]  # Last 5 errors
                    ]
                }
                
                # Check for critical patterns
                for log in error_logs:
                    if any(pattern in log['message'].lower() 
                          for pattern in ['fatal', 'crash', 'exception', 'failed to start']):
                        summary['critical_issues'].append({
                            'container': container_name,
                            'timestamp': log['timestamp'],
                            'message': log['message'],
                            'severity': 'critical'
                        })
        
        logger.info("Generated error summary", 
                   total_errors=summary['total_error_entries'],
                   containers_with_errors=summary['containers_with_errors'])
        
        return summary


def create_afas_log_collector() -> RemoteLogCollector:
    """Create a log collector for AFAS production server.
    
    Uses environment variables for configuration.
    
    Returns:
        Configured RemoteLogCollector instance
    """
    host = os.getenv('HETZNER_HOST')
    username = os.getenv('HETZNER_USER')
    ssh_key = os.getenv('HETZNER_SSH_KEY')
    
    if not all([host, username, ssh_key]):
        raise ValueError("Missing required environment variables: HETZNER_HOST, HETZNER_USER, HETZNER_SSH_KEY")
    
    return RemoteLogCollector(host=host, username=username, ssh_key=ssh_key)