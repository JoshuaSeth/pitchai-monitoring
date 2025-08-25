"""Docker log collection using bash commands for same-server deployment."""

import json
import re
import subprocess
from datetime import datetime, timedelta
from typing import Any

import structlog

from ..config import get_config

logger = structlog.get_logger(__name__)


class LogEntry:
    """Represents a single log entry from a container."""

    def __init__(
        self,
        container_name: str,
        timestamp: datetime,
        message: str,
        level: str | None = None,
        source: str | None = None
    ):
        self.container_name = container_name
        self.timestamp = timestamp
        self.message = message
        self.level = level
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        """Convert log entry to dictionary."""
        return {
            "container_name": self.container_name,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "level": self.level,
            "source": self.source
        }


class BashDockerLogCollector:
    """Collects logs from Docker containers using bash commands."""

    def __init__(self):
        self.config = get_config()

    def _run_command(self, command: list[str]) -> str:
        """Execute a bash command and return the output."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error("Command failed", command=" ".join(command), error=e.stderr)
            return ""
        except subprocess.TimeoutExpired:
            logger.error("Command timed out", command=" ".join(command))
            return ""

    def get_running_containers(self) -> list[str]:
        """Get list of currently running container names using docker ps."""
        command = ["docker", "ps", "--format", "{{.Names}}"]
        output = self._run_command(command)

        if not output:
            logger.warning("No running containers found or docker command failed")
            return []

        container_names = [name.strip() for name in output.split('\n') if name.strip()]
        logger.info("Found running containers", count=len(container_names), names=container_names)
        return container_names

    def get_container_info(self) -> list[dict[str, str]]:
        """Get detailed info about running containers."""
        command = ["docker", "ps", "--format", "json"]
        output = self._run_command(command)

        containers = []
        if output:
            for line in output.split('\n'):
                if line.strip():
                    try:
                        container_info = json.loads(line)
                        containers.append({
                            "name": container_info.get("Names", ""),
                            "image": container_info.get("Image", ""),
                            "status": container_info.get("Status", ""),
                            "ports": container_info.get("Ports", "")
                        })
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse container info", line=line)

        return containers

    def get_container_logs(
        self,
        container_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        tail: int | None = None
    ) -> list[LogEntry]:
        """Get logs from a specific container using docker logs command."""
        command = ["docker", "logs", "--timestamps"]

        if since:
            # Docker expects RFC3339 format
            since_str = since.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            command.extend(["--since", since_str])

        if until:
            until_str = until.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            command.extend(["--until", until_str])

        if tail:
            command.extend(["--tail", str(tail)])

        command.append(container_name)

        logger.debug("Collecting logs", container=container_name, command=" ".join(command))

        output = self._run_command(command)
        if not output:
            logger.warning("No logs found for container", container=container_name)
            return []

        # Parse logs into LogEntry objects
        log_entries = []
        for line in output.split('\n'):
            if not line.strip():
                continue

            entry = self._parse_log_line(container_name, line)
            if entry:
                log_entries.append(entry)

        logger.info("Collected logs", container=container_name, count=len(log_entries))
        return log_entries

    def _parse_log_line(self, container_name: str, line: str) -> LogEntry | None:
        """Parse a single log line into a LogEntry."""
        try:
            # Docker logs with timestamps format: timestamp message
            # Example: 2025-08-16T14:35:22.123456789Z [INFO] Application started

            # Split on first space to separate timestamp from message
            parts = line.split(' ', 1)
            if len(parts) < 2:
                return None

            timestamp_str = parts[0]
            message = parts[1]

            # Parse timestamp
            try:
                # Handle different timestamp formats
                if timestamp_str.endswith('Z'):
                    # Remove nanoseconds if present for parsing
                    if '.' in timestamp_str:
                        base_time = timestamp_str.split('.')[0]
                        timestamp = datetime.fromisoformat(base_time.replace('Z', '+00:00'))
                    else:
                        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                # Fallback to current time if parsing fails
                timestamp = datetime.utcnow()

            # Extract log level if present
            level = None
            level_patterns = [
                r'\[(\w+)\]',  # [INFO], [ERROR], etc.
                r'(\w+):',     # INFO:, ERROR:, etc.
                r'level=(\w+)', # level=info, level=error, etc.
            ]

            for pattern in level_patterns:
                match = re.search(pattern, message, re.IGNORECASE)
                if match:
                    level = match.group(1).upper()
                    break

            # Detect error patterns even without explicit level
            if not level:
                error_patterns = self.config.container_monitoring.error_keywords
                message_lower = message.lower()
                for keyword in error_patterns:
                    if keyword.lower() in message_lower:
                        level = "ERROR"
                        break

            return LogEntry(
                container_name=container_name,
                timestamp=timestamp,
                message=message,
                level=level
            )

        except Exception as e:
            logger.warning("Failed to parse log line", line=line, error=str(e))
            return None

    def collect_logs_for_timeframe(
        self,
        containers: list[str] | None = None,
        hours_back: int = 1
    ) -> dict[str, list[LogEntry]]:
        """Collect logs from multiple containers for a specific timeframe."""
        if containers is None:
            if self.config.auto_discover_containers:
                containers = self.get_running_containers()
            else:
                containers = self.config.docker_containers

        if not containers:
            logger.warning("No containers specified for log collection")
            return {}

        since = datetime.utcnow() - timedelta(hours=hours_back)

        logger.info("Collecting logs for timeframe", containers=containers, hours_back=hours_back)

        container_logs = {}
        for container_name in containers:
            try:
                logs = self.get_container_logs(container_name, since=since)
                container_logs[container_name] = logs
            except Exception as e:
                logger.error("Failed to collect logs", container=container_name, error=str(e))
                container_logs[container_name] = []

        total_logs = sum(len(logs) for logs in container_logs.values())
        logger.info("Collected all logs", total_entries=total_logs)

        return container_logs

    def filter_logs_by_level(self, log_entries: list[LogEntry], levels: list[str]) -> list[LogEntry]:
        """Filter log entries by log level."""
        levels_upper = [level.upper() for level in levels]
        filtered = [
            entry for entry in log_entries
            if entry.level and entry.level.upper() in levels_upper
        ]

        logger.debug("Filtered logs by level", original=len(log_entries), filtered=len(filtered))
        return filtered

    def filter_logs_by_pattern(self, log_entries: list[LogEntry], pattern: str) -> list[LogEntry]:
        """Filter log entries by message pattern."""
        pattern_lower = pattern.lower()
        filtered = [
            entry for entry in log_entries
            if pattern_lower in entry.message.lower()
        ]

        logger.debug("Filtered logs by pattern", original=len(log_entries), filtered=len(filtered), pattern=pattern)
        return filtered

    def get_error_summary(self, container_logs: dict[str, list[LogEntry]]) -> dict[str, Any]:
        """Generate an error summary for AI agent consumption."""
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_containers": len(container_logs),
            "containers_with_errors": 0,
            "total_errors": 0,
            "error_breakdown": {},
            "critical_issues": []
        }

        for container_name, logs in container_logs.items():
            error_logs = [log for log in logs if log.level == "ERROR"]

            if error_logs:
                summary["containers_with_errors"] += 1
                summary["total_errors"] += len(error_logs)
                summary["error_breakdown"][container_name] = {
                    "error_count": len(error_logs),
                    "recent_errors": [
                        {
                            "timestamp": log.timestamp.isoformat(),
                            "message": log.message[:200] + "..." if len(log.message) > 200 else log.message
                        }
                        for log in error_logs[-5:]  # Last 5 errors
                    ]
                }

                # Identify critical issues
                critical_keywords = ["fatal", "exception", "crashed", "failed to start", "connection refused"]
                for log in error_logs:
                    for keyword in critical_keywords:
                        if keyword in log.message.lower():
                            summary["critical_issues"].append({
                                "container": container_name,
                                "timestamp": log.timestamp.isoformat(),
                                "message": log.message,
                                "severity": "critical"
                            })
                            break

        return summary


# For backward compatibility, alias the new class
DockerLogCollector = BashDockerLogCollector
