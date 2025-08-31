# Autopar Staging Monitoring System

## Overview

The Autopar Staging Monitoring System is a specialized monitoring agent that runs in parallel with the main production monitoring system. It focuses specifically on monitoring the staging.autopar.pitchai.net website and its associated Docker containers.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Monitoring Schedule                       │
├─────────────────────────────────────────────────────────────┤
│ 03:00 UTC - Main Production Monitoring                     │
│ 03:15 UTC - Autopar Staging Monitoring                     │
│ 10:15 UTC - Main Production Monitoring                     │
│ 10:30 UTC - Autopar Staging Monitoring                     │
└─────────────────────────────────────────────────────────────┘
```

## Components Monitored

### 🌐 Website Health
- **URL**: staging.autopar.pitchai.net
- **Checks**: HTTP response, content validation, endpoint testing
- **Monitoring**: Response times, error detection, accessibility

### 🐳 Docker Containers
- **autopar-redis**: Redis database service
- **autopar-rabbitmq**: RabbitMQ message broker service
- **Health Checks**: Container status, resource usage, log analysis

### 📊 System Analysis
- Container logs with error pattern detection
- Resource usage monitoring (CPU, memory)
- Service dependency analysis
- Error correlation and trending

## Files and Components

### Core Scripts
- **`autopar_monitoring_agent.py`** - Main monitoring agent for autopar staging
- **`python_scheduler.py`** - Updated scheduler with autopar monitoring jobs
- **`main.py`** - Updated FastAPI server with autopar endpoints

### Configuration
- Uses same `.env` file for Telegram credentials
- Same notification system as main monitoring
- Separate analysis focused on autopar services

## Usage

### Manual Execution
```bash
# Run autopar monitoring (dry-run mode)
python3 autopar_monitoring_agent.py --dry-run --hours 4

# Run autopar monitoring (live mode)
python3 autopar_monitoring_agent.py --hours 4
```

### API Endpoints
```bash
# Trigger autopar monitoring via API
curl -X POST "http://localhost:8000/run/autopar-monitoring?hours=4"

# Or via GET request
curl "http://localhost:8000/run/autopar-monitoring?hours=4"
```

### Scheduled Execution
The system automatically runs via Python scheduler:
- **Morning**: 03:15 UTC (15 minutes after main monitoring)
- **Afternoon**: 10:30 UTC (15 minutes after main monitoring)

## Claude AI Integration

### Analysis Types
The autopar monitoring agent uses the same Claude AI analysis as the main system:

1. **STATUS: ALL_GOOD** - Autopar staging environment healthy
2. **STATUS: SUSPICIOUS_INVESTIGATE** - Warning patterns detected
3. **STATUS: ERRORS_INVESTIGATE** - Critical issues found

### Investigation Process
- Claude analyzes autopar-specific data
- Launches monitoring-infra-engineer for deep investigation when needed
- READ-ONLY investigation to prevent production disruption
- Comprehensive reporting with autopar-specific recommendations

## Telegram Notifications

### Message Format
```
🟢 AUTOPAR MONITORING - ALL SYSTEMS HEALTHY

📅 Report Time: 2025-08-31 18:00 UTC
⏱️ Period Analyzed: 4 hours
🎯 Environment: Autopar Staging
🤖 Analysis: Claude AI autopar monitoring

✅ Website: staging.autopar.pitchai.net accessible
✅ Redis: autopar-redis container healthy  
✅ RabbitMQ: autopar-rabbitmq container healthy
✅ Logs: No critical errors detected

🌐 Website: staging.autopar.pitchai.net
🐳 Containers: autopar-redis, autopar-rabbitmq

🔄 Next Check: 19:00 UTC

_Automated autopar monitoring by Claude Code Agent_
```

## Error Patterns

### Autopar-Specific Patterns
The system monitors for these autopar-specific issues:

- **Website Issues**: HTTP errors, timeout, content problems
- **Redis Issues**: Connection errors, memory issues, persistence problems
- **RabbitMQ Issues**: Memory watermarks, queue problems, connection failures
- **Container Issues**: Crashes, restarts, resource exhaustion

### Critical Patterns
- `website inaccessible`
- `container not running`  
- `connection refused`
- `authentication failed`
- `redis error`
- `rabbitmq error`

### Warning Patterns
- `memory_high_watermark`
- `alarm_handler`
- `retry`
- `timeout`
- `degraded`

## Testing

### System Test
```bash
python3 test_dual_monitoring.py
```

This tests:
- Autopar monitoring agent execution
- Main monitoring agent execution  
- FastAPI endpoint configuration
- Scheduler integration

### Individual Component Tests
```bash
# Test autopar agent only
python3 autopar_monitoring_agent.py --dry-run --hours 1

# Test main agent only  
python3 claude_monitoring_agent.py --dry-run --hours 1
```

## Integration Benefits

### Parallel Monitoring
- Main system monitors all production services
- Autopar system focuses specifically on staging.autopar.pitchai.net
- Both systems run independently but share infrastructure

### Specialized Analysis
- Autopar-specific error patterns
- Container-focused monitoring
- Website health validation
- Targeted alerting

### Complementary Scheduling
- 15-minute offset prevents resource conflicts
- Ensures continuous monitoring coverage
- Allows for correlation between systems

## Troubleshooting

### Common Issues

1. **Agent not executing**
   - Check Python environment
   - Verify file permissions
   - Check .env file configuration

2. **No Telegram notifications**
   - Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
   - Check internet connectivity
   - Test with dry-run mode first

3. **Container logs not accessible**
   - Verify Docker daemon running
   - Check container names match configuration
   - Ensure user has Docker access permissions

### Debug Mode
```bash
# Run with verbose output
python3 autopar_monitoring_agent.py --dry-run --hours 1
```

## Future Enhancements

### Potential Additions
- UI test integration for staging.autopar.pitchai.net
- Database query monitoring
- API endpoint performance testing
- Custom autopar-specific metrics collection
- Integration with other autopar environments (production, development)