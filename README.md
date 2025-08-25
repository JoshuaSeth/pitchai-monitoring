# Production Monitoring System

A comprehensive monitoring infrastructure for running UI tests and collecting logs from production systems. This system provides automated monitoring capabilities with structured reporting for team leads and operations engineers.

## Features

- **UI Testing**: Automated Playwright-based tests against production environments
- **Log Collection**: Docker container log collection and analysis
- **Incident Tracking**: Automatic incident creation and management for test failures
- **Reporting**: Structured JSON reports for team lead consumption
- **Scheduling**: Automated test runs and log collection on configurable schedules
- **Web API**: FastAPI-based REST API for manual triggering and status monitoring
- **CLI Tools**: Standalone scripts for individual operations

## Installation

1. **Install Dependencies**:
   ```bash
   uv sync
   ```

2. **Install Playwright Browsers**:
   ```bash
   uv run playwright install
   ```

3. **Setup Configuration**:
   ```bash
   cp config/monitoring.yaml config/monitoring-local.yaml
   # Edit config/monitoring-local.yaml with your settings
   export MONITORING_CONFIG=config/monitoring-local.yaml
   ```

## Quick Start

### Running the Web Server
Start the monitoring system with web interface:
```bash
uv run python main.py
```

The web interface will be available at http://localhost:8000

### CLI Usage
Run individual monitoring tasks:

```bash
# Run UI tests
uv run python main.py test

# Collect logs (last 2 hours)
uv run python main.py logs 2

# Generate daily report
uv run python main.py report

# Check system status
uv run python main.py status
```

### Standalone Scripts
Execute individual components:

```bash
# Run UI tests only
uv run python scripts/run_tests.py

# Collect Docker logs
uv run python scripts/collect_logs.py --hours 4 --errors-only

# Generate daily report
uv run python scripts/daily_report.py

# Generate comprehensive master report with UI tests + logs
uv run python master_log_aggregator.py --hours 4 --save
```

## Configuration

### Environment Variables
- `MONITORING_CONFIG`: Path to configuration file (default: `config/monitoring.yaml`)
- `MONITORING_ENV`: Environment name (default: `production`)
- `LOG_LEVEL`: Logging level (default: `INFO`)
- `DOCKER_HOST`: Docker daemon URL for remote connections
- `UI_TEST_TIMEOUT`: UI test timeout in seconds
- `BROWSER_HEADLESS`: Run browser in headless mode (`true`/`false`)

### Configuration File
Edit `config/monitoring.yaml` to customize:

```yaml
# Environment settings
environment: "production"
log_level: "INFO"

# UI Testing settings
ui_test_timeout: 30
browser_headless: true
screenshot_on_failure: true

# Docker settings
docker_containers:
  - "web-app"
  - "api-server"
  - "database"

# Scheduling
test_schedule_cron: "0 */1 * * *"  # Every hour
log_collection_interval: 300       # 5 minutes

# Production URLs
production_urls:
  - "https://your-production-app.com"
```

## Master Log Aggregator

### Overview
The **Master Log Aggregator** (`master_log_aggregator.py`) is the central component that combines UI test results with comprehensive system monitoring into a single, unified report. This tool automatically executes UI tests, collects container logs, system metrics, and error analysis into one comprehensive document.

### Key Features
- **UI Test Integration**: Automatically runs UI tests and prioritizes failures at the top of reports
- **Container Log Collection**: Aggregates logs from all monitored Docker containers
- **System Metrics**: Collects disk usage, memory, CPU load, and process information
- **Error Analysis**: Identifies and highlights critical issues from logs
- **Network Information**: Captures network interface and port status
- **Failure Prioritization**: Failed UI tests are prominently displayed with detailed error information

### Usage

#### Basic Usage
```bash
# Generate comprehensive report for last 4 hours
python master_log_aggregator.py --hours 4 --save

# Preview report without saving
python master_log_aggregator.py --hours 2 --preview

# Generate and save with custom filename
python master_log_aggregator.py --hours 6 --save --output custom_report.txt
```

#### Command Line Options
- `--hours N`: Hours of logs to collect (default: 4)
- `--save`: Save report to file in `reports/` directory
- `--output FILENAME`: Custom output filename
- `--preview`: Show preview of first 1000 characters

### Report Structure
The generated report contains the following sections in order:

1. **UI Test Results** (⚠️ **Prioritized if failures detected**):
   - Current test execution results
   - Failed test details with full error messages
   - Historical test result context
   - Test timing and performance data

2. **System Metrics**:
   - Disk space usage across all mounts
   - Memory utilization
   - CPU load averages
   - Top CPU-consuming processes

3. **Docker Status**:
   - Docker daemon status and version
   - Container disk usage statistics
   - Running container summary
   - Container health status

4. **Production Container Logs**:
   - Logs from all monitored containers
   - Recent log entries (last 10 per container)
   - Total log entry counts
   - Container-specific error detection

5. **Error Analysis**:
   - Critical error detection across all containers
   - Error breakdown by container
   - Recent error patterns and trends
   - Issue severity assessment

6. **Network Information**:
   - Network interface configuration
   - Listening ports and services
   - Network connectivity status

### Failure Detection and Prioritization

#### UI Test Failures
When UI tests fail, the Master Log Aggregator:
- **Elevates Priority**: Failed tests get top-level header prominence
- **Shows Detailed Errors**: Full error messages, stack traces, and failure context
- **Provides Screenshots**: Links to failure screenshots when available
- **Includes Timing**: Test execution duration and timeout information
- **Historical Context**: Shows recent test result trends

#### Critical Issue Detection
The system identifies critical issues through:
- **Exit Code Analysis**: Non-zero exit codes indicate test failures
- **Content Parsing**: Searches for error keywords in output
- **Log Pattern Matching**: Identifies ERROR, FATAL, Exception patterns in logs
- **System Threshold Monitoring**: Detects resource exhaustion scenarios

### Output Files
Master Log Aggregator reports are saved as:
- **Location**: `reports/master_log_report_YYYYMMDD_HHMMSS.txt`
- **Format**: Structured text with clear section headers
- **Size**: Typically 50-100KB depending on log volume
- **Content**: Human-readable format optimized for operations teams

### Integration with Monitoring System
The Master Log Aggregator is currently a **standalone tool** with future integration planned:

#### Current Status
- **Standalone Execution**: Run independently via command line
- **Manual Triggering**: No API integration yet implemented
- **Scheduled Execution**: Supports cron-based automated execution
- **Agent Ready**: Designed for future AI agent consumption

#### Planned Integration
- **API Endpoint**: Future `/run/master-report` endpoint
- **Task Coordinator**: Integration with task scheduling system
- **Background Processing**: Async execution via FastAPI background tasks
- **Report Correlation**: Automatic linking with incident management

### Production Deployment
For production use:

```bash
# Daily comprehensive report
0 6 * * * cd /path/to/monitoring && python master_log_aggregator.py --hours 24 --save

# Hourly critical monitoring
0 * * * * cd /path/to/monitoring && python master_log_aggregator.py --hours 1 --save
```

### Troubleshooting
Common issues with Master Log Aggregator:

**UI Tests Not Running**: 
- Verify Playwright installation: `npx playwright install`
- Check test file permissions and syntax

**Container Log Access Issues**:
- Verify Docker daemon connectivity
- Check SSH keys for remote log collection
- Ensure proper container permissions

**Report Generation Failures**:
- Check write permissions to `reports/` directory
- Verify sufficient disk space
- Review system resource availability

**Empty or Incomplete Reports**:
- Increase timeout values for slow systems
- Check network connectivity for remote resources
- Verify container names and accessibility

### Future Enhancements
The Master Log Aggregator is designed for future agent integration:
- **AI Agent Consumption**: Structured output ready for automated analysis
- **Alert Generation**: Automatic notification of critical failures
- **Trend Analysis**: Historical data comparison and pattern detection
- **Predictive Monitoring**: Early warning system development

## Creating UI Tests

### Test File Format
Create test files in the `tests/` directory using YAML format:

```yaml
flow_name: "Login — Successful Authentication"
description: "User can successfully log in with valid credentials"
target_url: "https://your-production-app.com/login"
target_env: "production"
owner: "Danny"
last_verified: "2025-08-16"

steps:
  - action: "navigate"
    value: "https://your-production-app.com/login"
    
  - action: "fill"
    selector: "#email-input"
    value: "test@example.com"
    
  - action: "click"
    selector: "#login-button"
    
  - action: "assert_visible"
    selector: ".dashboard"
```

### Supported Actions
- `navigate`: Navigate to URL
- `click`: Click an element
- `fill`: Fill input field
- `wait_for`: Wait for element to appear
- `assert_visible`: Assert element is visible
- `assert_text`: Assert element contains text
- `wait`: Wait for specified seconds

## API Endpoints

### Core Endpoints
- `GET /`: Health check
- `GET /status`: System status
- `POST /run/ui-tests`: Trigger UI test suite
- `POST /run/log-collection`: Trigger log collection
- `POST /run/daily-report`: Generate daily report
- `GET /tasks/{task_id}`: Get task status

### Planned Endpoints
- `POST /run/master-report`: **[Future]** Trigger comprehensive master log aggregation
- `GET /reports/latest-master`: **[Future]** Get latest master log aggregator report

### Example API Usage

```bash
# Check system status
curl http://localhost:8000/status

# Trigger UI tests
curl -X POST http://localhost:8000/run/ui-tests

# Collect logs from last 2 hours
curl -X POST "http://localhost:8000/run/log-collection?hours_back=2"

# Get task status
curl http://localhost:8000/tasks/ui_tests_20250816_143522
```

## Directory Structure

```
monitoring/
├── config/                 # Configuration files
├── creation/              # Test creation workspace
├── execution/             # Test execution logs
├── tests/                 # UI test definitions
├── incidents/             # Incident reports
├── logs/                  # Collected log files
├── reports/               # Generated reports
├── scripts/               # Standalone scripts
└── monitoring/            # Core package
    ├── ui_testing/        # UI test execution
    ├── log_collector/     # Log collection
    ├── reporting/         # Report generation
    └── scheduler/         # Task scheduling
```

## Output Files

### Master Log Aggregator Reports
- **Location**: `reports/master_log_report_YYYYMMDD_HHMMSS.txt`
- **Format**: Comprehensive text report with UI tests + logs + system metrics
- **Content**: Complete system status including prioritized test failures
- **Size**: 50-100KB depending on log volume and system activity
- **Usage**: Primary report for operations teams and future agent consumption

### Test Results
- **Location**: `reports/test_results_YYYYMMDD_HHMMSS.json`
- **Format**: Structured JSON with pass/fail data, screenshots, metadata
- **Content**: Test execution summary, individual results, failure analysis

### Log Files
- **Location**: `logs/logs_YYYYMMDD_HHMMSS.json`
- **Format**: JSON with container logs organized by container name
- **Content**: Log entries with timestamps, levels, messages

### Incident Reports
- **Location**: `incidents/INCIDENT_ID.json`
- **Format**: Structured incident data with correlation information
- **Content**: Test failure details, log correlation, investigation status

### Daily Reports
- **Location**: `reports/daily_summary_YYYY-MM-DD.json`
- **Format**: Executive summary for team leads
- **Content**: Overall statistics, issues, recommendations

## Incident Management

### Incident Workflow
1. **Automatic Creation**: Failed tests automatically create incidents
2. **Log Correlation**: System correlates failure time with container logs
3. **Team Lead Notification**: Daily reports highlight open incidents
4. **Investigation**: Ops engineers can update incident status
5. **Resolution Tracking**: Full audit trail of investigation steps

### Incident Statuses
- `open`: New incident requiring attention
- `investigating`: Under active investigation
- `identified`: Root cause identified
- `fixed`: Issue resolved
- `verified`: Fix verified in production
- `closed`: Incident fully resolved
- `false_positive`: Not a real issue

## Docker Integration

### Required Docker Access
The system needs access to Docker daemon to collect container logs:

```bash
# Local Docker
export DOCKER_HOST=unix:///var/run/docker.sock

# Remote Docker (secure)
export DOCKER_HOST=tcp://production-server:2376
export DOCKER_TLS_VERIFY=1
export DOCKER_CERT_PATH=/path/to/certs
```

### Container Configuration
Specify containers to monitor in configuration:

```yaml
docker_containers:
  - "web-application"
  - "api-server"
  - "background-worker"
  - "redis-cache"
  - "postgresql-db"
```

## Security Considerations

### Production Access
- Use environment variables for sensitive configuration
- Implement proper authentication for production URLs
- Secure Docker daemon access with TLS
- Restrict network access to monitoring system

### Authentication Tokens
Store sensitive tokens in environment variables:

```bash
export API_KEY="your-production-api-key"
export AUTH_TOKEN="your-auth-token"
```

Reference in configuration:
```yaml
auth_tokens:
  api_key: "${API_KEY}"
  auth_token: "${AUTH_TOKEN}"
```

## Troubleshooting

### Common Issues

**No tests found**: Check `tests/` directory has `.yaml` files with proper format

**Docker connection failed**: Verify `DOCKER_HOST` and daemon accessibility

**UI tests timeout**: Increase `ui_test_timeout` in configuration

**Playwright issues**: Run `uv run playwright install` to install browsers

**Permission errors**: Ensure write access to `reports/`, `logs/`, `incidents/` directories

### Debug Mode
Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
uv run python main.py
```

### Log Files
Check application logs for detailed error information:
- Web server logs in console output
- Individual task logs in structured format
- Playwright logs in test execution output

## Development

### Adding New Test Actions
Extend `ui_testing/runner.py` `_execute_step()` method:

```python
elif action == "custom_action":
    # Your custom logic here
    pass
```

### Custom Log Processors
Extend `log_collector/log_processor.py` for specialized log analysis:

```python
def analyze_custom_patterns(self, log_entries):
    # Your analysis logic
    pass
```

### Additional Report Types
Extend `reporting/report_generator.py` for specialized reports:

```python
def generate_custom_report(self, data):
    # Your report logic
    pass
```

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review log files for error details
3. Verify configuration settings
4. Ensure all dependencies are installed correctly

## Architecture

The system is built with a modular architecture:

- **Task Coordinator**: Orchestrates all monitoring activities
- **Job Scheduler**: Manages automated execution schedules  
- **UI Test Runner**: Executes Playwright-based tests
- **Log Collector**: Retrieves and processes Docker logs
- **Report Generator**: Creates structured output for team leads
- **Incident Tracker**: Manages failure investigation workflow

This design ensures scalability, maintainability, and clear separation of concerns for production monitoring needs.