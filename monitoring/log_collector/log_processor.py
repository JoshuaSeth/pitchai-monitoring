"""Log processing and analysis utilities."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from ..config import get_config
from .docker_logs import LogEntry

logger = structlog.get_logger(__name__)


class LogProcessor:
    """Processes and analyzes collected logs."""

    def __init__(self):
        self.config = get_config()

        # Common error patterns
        self.error_patterns = [
            re.compile(r'error', re.IGNORECASE),
            re.compile(r'exception', re.IGNORECASE),
            re.compile(r'failed', re.IGNORECASE),
            re.compile(r'timeout', re.IGNORECASE),
            re.compile(r'connection.*refused', re.IGNORECASE),
            re.compile(r'500.*internal.*server.*error', re.IGNORECASE),
            re.compile(r'404.*not.*found', re.IGNORECASE),
        ]

        # Warning patterns
        self.warning_patterns = [
            re.compile(r'warning', re.IGNORECASE),
            re.compile(r'deprecated', re.IGNORECASE),
            re.compile(r'slow.*query', re.IGNORECASE),
            re.compile(r'retry', re.IGNORECASE),
        ]

    def save_logs_to_file(
        self,
        container_logs: dict[str, list[LogEntry]],
        filename: str | None = None
    ) -> str:
        """Save collected logs to a JSON file."""
        if filename is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"logs_{timestamp}.json"

        logs_path = Path(self.config.logs_directory) / filename
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to serializable format
        serializable_logs = {}
        for container, logs in container_logs.items():
            serializable_logs[container] = [log.to_dict() for log in logs]

        with open(logs_path, 'w') as f:
            json.dump(serializable_logs, f, indent=2, default=str)

        logger.info("Saved logs to file", file=str(logs_path))
        return str(logs_path)

    def load_logs_from_file(self, filepath: str) -> dict[str, list[LogEntry]]:
        """Load logs from a JSON file."""
        with open(filepath) as f:
            data = json.load(f)

        container_logs = {}
        for container, logs_data in data.items():
            logs = []
            for log_data in logs_data:
                log_entry = LogEntry(
                    container_name=log_data['container_name'],
                    timestamp=datetime.fromisoformat(log_data['timestamp']),
                    message=log_data['message'],
                    level=log_data.get('level'),
                    source=log_data.get('source')
                )
                logs.append(log_entry)
            container_logs[container] = logs

        logger.info("Loaded logs from file", file=filepath)
        return container_logs

    def analyze_error_patterns(self, log_entries: list[LogEntry]) -> dict[str, Any]:
        """Analyze logs for error patterns and anomalies."""
        analysis = {
            "total_entries": len(log_entries),
            "errors": [],
            "warnings": [],
            "error_count": 0,
            "warning_count": 0,
            "analysis_timestamp": datetime.utcnow().isoformat()
        }

        for entry in log_entries:
            # Check for errors
            for pattern in self.error_patterns:
                if pattern.search(entry.message):
                    analysis["errors"].append({
                        "timestamp": entry.timestamp.isoformat(),
                        "container": entry.container_name,
                        "message": entry.message,
                        "level": entry.level,
                        "pattern": pattern.pattern
                    })
                    analysis["error_count"] += 1
                    break

            # Check for warnings
            for pattern in self.warning_patterns:
                if pattern.search(entry.message):
                    analysis["warnings"].append({
                        "timestamp": entry.timestamp.isoformat(),
                        "container": entry.container_name,
                        "message": entry.message,
                        "level": entry.level,
                        "pattern": pattern.pattern
                    })
                    analysis["warning_count"] += 1
                    break

        logger.info("Completed error pattern analysis",
                   errors=analysis["error_count"],
                   warnings=analysis["warning_count"])

        return analysis

    def find_logs_around_timestamp(
        self,
        log_entries: list[LogEntry],
        target_timestamp: datetime,
        window_minutes: int = 5
    ) -> list[LogEntry]:
        """Find logs within a time window around a specific timestamp."""
        start_time = target_timestamp - timedelta(minutes=window_minutes)
        end_time = target_timestamp + timedelta(minutes=window_minutes)

        filtered_logs = [
            entry for entry in log_entries
            if start_time <= entry.timestamp <= end_time
        ]

        # Sort by timestamp
        filtered_logs.sort(key=lambda x: x.timestamp)

        logger.debug("Found logs around timestamp",
                    target=target_timestamp.isoformat(),
                    window_minutes=window_minutes,
                    count=len(filtered_logs))

        return filtered_logs

    def correlate_with_test_failure(
        self,
        container_logs: dict[str, list[LogEntry]],
        failure_timestamp: datetime,
        window_minutes: int = 5
    ) -> dict[str, Any]:
        """Correlate container logs with a test failure timestamp."""
        correlation_data = {
            "failure_timestamp": failure_timestamp.isoformat(),
            "window_minutes": window_minutes,
            "containers": {},
            "potential_causes": []
        }

        for container_name, logs in container_logs.items():
            # Find logs around failure time
            relevant_logs = self.find_logs_around_timestamp(
                logs, failure_timestamp, window_minutes
            )

            # Analyze for errors
            error_analysis = self.analyze_error_patterns(relevant_logs)

            correlation_data["containers"][container_name] = {
                "log_count": len(relevant_logs),
                "error_count": error_analysis["error_count"],
                "warning_count": error_analysis["warning_count"],
                "errors": error_analysis["errors"]
            }

            # Add significant errors as potential causes
            for error in error_analysis["errors"]:
                correlation_data["potential_causes"].append({
                    "container": container_name,
                    "timestamp": error["timestamp"],
                    "message": error["message"],
                    "confidence": "high" if "error" in error["message"].lower() else "medium"
                })

        logger.info("Completed log correlation",
                   failure_time=failure_timestamp.isoformat(),
                   potential_causes=len(correlation_data["potential_causes"]))

        return correlation_data

    def generate_log_summary(self, container_logs: dict[str, list[LogEntry]]) -> dict[str, Any]:
        """Generate a summary of collected logs."""
        summary = {
            "collection_timestamp": datetime.utcnow().isoformat(),
            "containers": {},
            "total_logs": 0,
            "total_errors": 0,
            "total_warnings": 0
        }

        for container_name, logs in container_logs.items():
            if not logs:
                continue

            # Analyze container logs
            analysis = self.analyze_error_patterns(logs)

            # Calculate time range
            timestamps = [log.timestamp for log in logs]
            min_time = min(timestamps) if timestamps else None
            max_time = max(timestamps) if timestamps else None

            container_summary = {
                "log_count": len(logs),
                "error_count": analysis["error_count"],
                "warning_count": analysis["warning_count"],
                "time_range": {
                    "start": min_time.isoformat() if min_time else None,
                    "end": max_time.isoformat() if max_time else None
                },
                "log_levels": {}
            }

            # Count by log level
            for log in logs:
                level = log.level or "UNKNOWN"
                container_summary["log_levels"][level] = container_summary["log_levels"].get(level, 0) + 1

            summary["containers"][container_name] = container_summary
            summary["total_logs"] += len(logs)
            summary["total_errors"] += analysis["error_count"]
            summary["total_warnings"] += analysis["warning_count"]

        logger.info("Generated log summary",
                   containers=len(summary["containers"]),
                   total_logs=summary["total_logs"])

        return summary
