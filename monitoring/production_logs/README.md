# Production Log Collection Module

A **safe, non-invasive** module for collecting logs from production Docker containers via SSH. This module provides read-only access to production logs without affecting running containers.

## 🔒 Safety Features

- **READ-ONLY Operations**: Only safe Docker commands are allowed
- **Command Validation**: Explicit blocking of all destructive operations
- **SSH Security**: Secure remote access with key-based authentication
- **Non-Invasive**: No modifications to running containers
- **Comprehensive Logging**: Full audit trail of all operations

## 🚀 Quick Start

### Prerequisites

Set the required environment variables in your `.env` file:

```bash
HETZNER_HOST=37.27.67.52
HETZNER_USER=root
HETZNER_SSH_KEY="-----BEGIN OPENSSH PRIVATE KEY-----..."
```

### Basic Usage

```python
from monitoring.production_logs import LogInterface

# Initialize the interface
interface = LogInterface()

# Get recent logs from all containers (last hour)
logs = interface.get_recent_logs(hours=1)

# Get only error logs
errors = interface.get_recent_errors(hours=2)

# Get logs from a specific container
app_logs = interface.get_logs("web-app", hours=4)

# Save all logs to a file
file_path = interface.save_all_logs(hours=6)
```

### CLI Usage

```bash
# Check system status
python -m monitoring.production_logs.cli status

# Get recent logs (1 hour)
python -m monitoring.production_logs.cli logs

# Get logs from last 4 hours
python -m monitoring.production_logs.cli logs 4

# Check for errors
python -m monitoring.production_logs.cli errors

# Get logs from specific container
python -m monitoring.production_logs.cli container web-app 2

# Save logs to file
python -m monitoring.production_logs.cli save 6

# Health check
python -m monitoring.production_logs.cli health
```

## 📖 API Reference

### LogInterface Class

The main interface for log collection operations.

#### Methods

##### `get_containers() -> List[str]`
Get list of running container names.

##### `get_recent_logs(hours: int = 1) -> Dict[str, List[Dict]]`
Get recent logs from all containers.

**Parameters:**
- `hours`: Number of hours back to retrieve (default: 1)

**Returns:** Dictionary mapping container names to log entries

##### `get_recent_errors(hours: int = 1) -> Dict[str, List[Dict]]`
Get recent error logs from all containers.

##### `get_logs(container_name: str, hours: int = 1) -> List[Dict]`
Get logs from a specific container.

##### `get_error_summary(hours: int = 1) -> Dict[str, Any]`
Get comprehensive error summary across all containers.

##### `save_all_logs(hours: int = 1, filename: str = None) -> str`
Collect and save logs to a JSON file.

##### `check_health() -> bool`
Check if the log collection system is healthy.

### ProductionLogCollector Class

Lower-level collector with more detailed control.

#### Methods

##### `get_container_list() -> List[Dict[str, str]]`
Get detailed information about running containers.

##### `get_logs_from_container(container_name: str, hours_back: int = 1) -> List[Dict]`
Get logs from a specific container with detailed metadata.

##### `get_logs_from_all_containers(hours_back: int = 1) -> Dict[str, List[Dict]]`
Get logs from all containers.

##### `get_error_logs_only(hours_back: int = 1) -> Dict[str, List[Dict]]`
Filter and return only error-level logs.

##### `health_check() -> Dict[str, Any]`
Perform comprehensive health check with detailed status.

## 📊 Log Entry Format

Each log entry contains:

```python
{
    "container_name": "web-app",
    "timestamp": "2025-08-16T14:30:22.123456",
    "level": "ERROR",  # INFO, WARNING, ERROR, DEBUG
    "message": "Application error occurred",
    "raw_line": "2025-08-16T14:30:22.123456Z [ERROR] Application error occurred"
}
```

## 📁 Saved Log File Format

When saving logs to file, the format includes metadata:

```json
{
    "timestamp": "2025-08-16T14:35:22.123456",
    "collection_source": "production_ssh",
    "containers": {
        "web-app": [...],
        "api-server": [...],
        "database": [...]
    }
}
```

## 🔍 Error Summary Format

The error summary provides comprehensive analysis:

```python
{
    "timestamp": "2025-08-16T14:35:22.123456",
    "analysis_period_hours": 1,
    "total_containers": 5,
    "containers_with_errors": 2,
    "total_error_entries": 15,
    "error_breakdown": {
        "web-app": {
            "error_count": 10,
            "recent_errors": [...]
        }
    },
    "critical_issues": [
        {
            "container": "web-app",
            "timestamp": "2025-08-16T14:30:22.123456",
            "message": "Fatal error occurred",
            "severity": "critical"
        }
    ]
}
```

## 🛡️ Security & Safety

### Allowed Operations
- `docker ps` - List containers
- `docker logs` - Read container logs  
- `docker inspect` - Get container metadata
- `docker stats --no-stream` - Get container statistics

### Blocked Operations
- Any `docker exec` commands
- Container lifecycle operations (start, stop, restart, kill)
- Image operations (build, push, pull, rm)
- Volume operations
- Network modifications
- Any destructive operations

### Connection Security
- SSH key-based authentication
- Timeout protection on all operations
- Comprehensive error handling
- Full audit logging

## 🔧 Examples

### Example 1: Basic Health Check

```python
from monitoring.production_logs import LogInterface

interface = LogInterface()

# Check if system is ready
if interface.check_health():
    print("✅ System is ready")
    containers = interface.get_containers()
    print(f"Found {len(containers)} containers")
else:
    print("❌ System not ready")
```

### Example 2: Error Monitoring

```python
from monitoring.production_logs import LogInterface

interface = LogInterface()

# Check for errors in last 4 hours
errors = interface.get_recent_errors(hours=4)

if errors:
    print(f"Found errors in {len(errors)} containers")
    for container, error_logs in errors.items():
        print(f"{container}: {len(error_logs)} errors")
        
        # Show latest error
        if error_logs:
            latest = error_logs[-1]
            print(f"  Latest: {latest['message']}")
else:
    print("✅ No errors found")
```

### Example 3: Detailed Analysis

```python
from monitoring.production_logs import ProductionLogCollector

collector = ProductionLogCollector()

# Get comprehensive error summary
summary = collector.get_error_summary(hours=6)

print(f"Analysis Results:")
print(f"  Containers monitored: {summary['total_containers']}")
print(f"  Containers with errors: {summary['containers_with_errors']}")
print(f"  Total error entries: {summary['total_error_entries']}")
print(f"  Critical issues: {len(summary['critical_issues'])}")

# Show critical issues
for issue in summary['critical_issues']:
    print(f"  🔥 {issue['container']}: {issue['message'][:80]}...")
```

### Example 4: Convenience Functions

```python
from monitoring.production_logs.log_interface import (
    get_production_logs, 
    get_production_errors, 
    save_production_logs
)

# Quick access functions
logs = get_production_logs(hours=2)  # Last 2 hours
errors = get_production_errors(hours=1)  # Last hour errors
saved_file = save_production_logs(hours=4)  # Save 4 hours to file
```

## 🚨 Error Handling

The module includes comprehensive error handling:

```python
from monitoring.production_logs import LogInterface

interface = LogInterface()

try:
    logs = interface.get_recent_logs(hours=1)
except RuntimeError as e:
    print(f"Log collection failed: {e}")
except ValueError as e:
    print(f"Configuration error: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## 📋 Troubleshooting

### Common Issues

**SSH Connection Failed**
- Verify `HETZNER_HOST`, `HETZNER_USER`, and `HETZNER_SSH_KEY` environment variables
- Check network connectivity to production server
- Ensure SSH key format is correct

**No Containers Found**
- Check if Docker daemon is running on production server
- Verify user has permission to access Docker

**Permission Denied**
- Ensure SSH user has proper permissions
- Check Docker group membership on remote server

### Debug Mode

Enable debug logging:

```python
import structlog

# Configure debug logging
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(10)  # DEBUG level
)

# Now use the interface
from monitoring.production_logs import LogInterface
interface = LogInterface()
```

## 📦 Module Structure

```
monitoring/production_logs/
├── __init__.py              # Module exports
├── production_log_collector.py  # Core collector class
├── log_interface.py         # Simple interface  
├── cli.py                   # Command-line tool
├── example_usage.py         # Usage examples
└── README.md               # This file
```

## 🔗 Integration

This module integrates seamlessly with the existing monitoring system and can be used:

- As a standalone log collection tool
- Integrated into the main monitoring workflow
- Via CLI for manual operations
- Through the web API endpoints
- In custom scripts and automation

## ⚡ Performance

- Efficient SSH connection management with context managers
- Configurable log collection timeframes
- Structured logging for performance monitoring
- Minimal memory footprint for log processing
- Optimized for production environments

---

**Note**: This module is designed for **read-only access** and maintains strict safety guarantees. All operations are non-invasive and will not affect running production containers.