# PitchAI Monitoring System

A comprehensive monitoring system powered by Claude AI for production deployments.

## Features

- Claude-powered analysis and reporting
- UI testing with Playwright
- Container log collection
- Telegram notifications
- Production health monitoring

## System Architecture Overview

**Core Purpose**: Automated production monitoring with AI-powered analysis, UI testing, and intelligent alerting

## Key Components

### 1. SCHEDULING LAYER 
- **Python Scheduler** (`python_scheduler.py`): Primary scheduler using `schedule` library
  - Main monitoring: 04:00 UTC & 11:00 UTC daily (05:00 & 12:00 Amsterdam time)
  - Autopar monitoring: 04:15 UTC & 11:15 UTC daily (05:15 & 12:15 Amsterdam time, 15min offset)
  - Quickchat monitoring: 04:30 UTC & 11:30 UTC daily (05:30 & 12:30 Amsterdam time, 30min offset)
- **GitHub Actions** (CI/CD): Automated deployment on main branch push
- **Manual Triggers**: HTTP endpoints for on-demand execution

### 2. MONITORING AGENTS
- **`claude_monitoring_agent.py`**: Main AI-powered monitoring using Claude CLI
  - Collects logs, runs tests, analyzes with Claude
  - Makes decisions: ALL_GOOD, SUSPICIOUS_INVESTIGATE, or ERRORS_INVESTIGATE
  - Can launch infrastructure investigation agents
- **`autopar_monitoring_agent.py`**: Specialized for Autopar staging environment
- **`quickchat_monitoring_agent.py`**: Specialized for Quickchat system monitoring
  - Monitors chat.pitchai.net website and chat functionality
  - Runs chat interaction UI tests (chat_interaction_test.spec.js)
  - Analyzes chat container logs and system health
- **`master_log_aggregator.py`**: Comprehensive data collection orchestrator

### 3. DATA COLLECTION
- **Docker Logs**: Direct container log access via Docker socket
- **System Metrics**: CPU, memory, disk usage monitoring
- **UI Tests**: Playwright-based browser automation tests
- **Production Logs Module**: SSH-based remote log collection
- **Error Analysis**: Pattern detection and critical issue identification

### 4. UI TESTING INFRASTRUCTURE
- **Playwright Framework**: Browser automation with Chromium
- **Test Files**:
  - `chat_interaction_test.spec.js`: Chat widget monitoring
  - `afasask-critical-journey.spec.js`: DM campaign analysis flow
- **Session Recording**: Converts browser sessions to permanent tests

### 5. NOTIFICATION SYSTEM
- **Telegram Integration**: Real-time alerts to team
- **Markdown to HTML Conversion**: Rich formatting support
- **Severity Levels**: INFO, WARNING, ERROR, CRITICAL
- **Morning Reports**: Daily health summaries

### 6. WEB API (`main.py` - FastAPI)
- **Health Endpoints**: `/`, `/status`, `/health/docker`
- **Monitoring Triggers**: 
  - `/run/claude-monitoring` - Main AI monitoring
  - `/run/autopar-monitoring` - Autopar specific
  - `/run/quickchat-monitoring` - Quickchat system specific
  - `/run/ui-tests` - UI test suite
- **Report Access**: `/reports/latest-ai-summary`

## Workflow Execution Flow

```
Morning (04:00 UTC / 05:00 Amsterdam) / Afternoon (11:00 UTC / 12:00 Amsterdam)
    ↓
Python Scheduler triggers
    ↓
claude_monitoring_agent.py executes
    ↓
master_log_aggregator.py collects:
    • Docker logs (all containers)
    • System metrics (disk/memory/CPU)
    • UI test results (Playwright)
    • Error summaries
    ↓
Claude AI analyzes data (up to 2 hours)
    ↓
Decision branching:
    • ALL_GOOD → Green status to Telegram
    • SUSPICIOUS → Investigation + Yellow alert
    • ERRORS → Deep investigation + Red alert
    ↓
Telegram notification sent to team
```

## Monitoring Coverage

**Production Containers Monitored**:
- PostgreSQL database
- Redis cache
- Application containers (autopar, afasask)
- Supporting services (RabbitMQ, etc.)

**UI Tests Coverage**:
- Chat widget functionality
- User authentication flows
- Critical user journeys
- API response validation

**System Health Checks**:
- Disk space monitoring (critical after recent 100% incident)
- Memory usage patterns
- Container health status
- Network connectivity

## Deployment

**Docker Container**:
- Python 3.12 base image
- Playwright browsers installed
- Node.js for Claude CLI
- Python-based scheduling (no cron dependency)
- Volume mounts for Docker socket access

**GitHub Actions CI/CD**:
- Auto-deploys on main branch push
- Direct SSH deployment to Hetzner server
- Container replacement strategy
- Environment variable injection

The system is automatically deployed via GitHub Actions to production infrastructure.

## Safety Features

- **Read-only operations** for production monitoring
- **Timeout protection** (2-hour max for Claude analysis)
- **Error handling** with fallback pattern analysis
- **Multiple scheduling redundancy**
- **Comprehensive logging** to track all operations

## Key Insights

1. **Streamlined scheduling**: Single Python scheduler + manual triggers (no duplicate messages)
2. **AI-first approach**: Claude analyzes all data and makes decisions
3. **Proactive monitoring**: Runs automatically twice daily
4. **Comprehensive coverage**: Logs + metrics + UI tests + error analysis
5. **Smart alerting**: Only notifies on real issues, not noise
6. **Session-to-test conversion**: UI interactions become permanent tests
7. **Production-safe**: All operations are read-only

This system represents a sophisticated, production-grade monitoring solution that combines traditional metrics with AI analysis and automated UI testing to provide comprehensive coverage of critical production systems.