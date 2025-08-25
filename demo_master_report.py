#!/usr/bin/env python3
"""
Demo Master Log Report - Shows the concept with sample production data

This demonstrates what the master log aggregator will look like when fully working.
"""

import os
from datetime import datetime


def create_section(title: str, content: str, level: int = 1) -> str:
    """Create a formatted section"""
    separators = {1: "=", 2: "-", 3: "."}
    sep = separators.get(level, "=")

    return f"""
{sep*80}
{title.upper() if level == 1 else title}
{sep*80}
{content}
"""

def main():
    """Generate a demo master log report with sample data"""

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    print("🎭 Generating Demo Master Log Report...")
    print("=" * 50)

    sections = []

    # Header
    header = f"""PITCHAI PRODUCTION MONITORING - MASTER LOG REPORT
Generated: {timestamp}
Time Period: 4 hours
Report Type: Comprehensive System & Application Analysis

This report aggregates data from:
• 17 Production Docker containers (SSH remote access)
• Container logs with error analysis and annotations
• System metrics (disk, memory, CPU, network)
• Application-specific monitoring data
• Security and performance indicators

Report sections:
1. Production Container Status & Health
2. Container Logs (annotated by container)
3. Error Analysis & Critical Issues
4. System Resource Utilization
5. Network & Connectivity Status
6. Summary & Recommendations"""

    sections.append(create_section("Master Report Overview", header))

    # Production Container Status
    container_status = """PRODUCTION SERVER: 37.27.67.52 (Hetzner)
SSH Connection: ✅ Active
Docker Daemon: ✅ Running
Total Containers: 17

CONTAINER STATUS SUMMARY:
📦 afasask                          | Status: Up 2 days (unhealthy)    | Ports: 3102
📦 afasask-staging                   | Status: Up 2 days (unhealthy)    | Ports: 3105
📦 autopar-staging                   | Status: Up 4 days                | Ports: 3103
📦 autopar                          | Status: Up 10 days               | Ports: 3101
📦 metabase                         | Status: Up 2 weeks               | Ports: 3200
📦 ai-price-crawler-match-ops-1     | Status: Up 3 weeks (unhealthy)   | No ports
📦 ai-price-crawler-matcher-1       | Status: Up 3 weeks               | No ports
📦 ai-price-crawler-adder-1         | Status: Up 3 weeks               | No ports
📦 ai-price-crawler-crawler-1       | Status: Restarting (1)           | No ports
📦 meilisearch                      | Status: Up 3 weeks               | Ports: 7700
📦 portainer                        | Status: Up 3 weeks               | Ports: 9443
📦 afasask-quick-chat               | Status: Up 3 weeks (unhealthy)   | Ports: 3106
📦 postgres-container               | Status: Up 12 days               | Ports: 5432
📦 deplanbook                       | Status: Up 3 weeks               | Ports: 3130
📦 aipc                             | Status: Up 3 weeks               | Ports: 3120
📦 registry                         | Status: Up 3 weeks               | Ports: 5000
📦 qdrant                           | Status: Up 3 weeks               | Ports: 6333-6334

⚠️  HEALTH ALERTS:
• 4 containers showing unhealthy status
• 1 container in restart loop (ai-price-crawler-crawler-1)
• No critical port conflicts detected"""

    sections.append(create_section("Production Container Status", container_status))

    # Container Logs (annotated)
    container_logs = """LOG COLLECTION PERIOD: Last 4 hours
TOTAL LOG ENTRIES: 1,247 across 17 containers
CONTAINERS WITH ACTIVITY: 8/17

>>> CONTAINER: METABASE <<<
Log entries: 856
Status: Active logging
Recent activity:
[2025-08-17 18:45:22] INFO: Query execution completed in 234ms
[2025-08-17 18:45:18] INFO: Database connection pool status: 8/10 active
[2025-08-17 18:45:15] INFO: User authentication successful: user_id=12
[2025-08-17 18:45:10] INFO: Dashboard loaded: analytics_overview
[2025-08-17 18:45:05] INFO: Scheduled report generation started
...and 851 more entries

>>> CONTAINER: POSTGRES-CONTAINER <<<
Log entries: 234
Status: Database activity normal
Recent activity:
[2025-08-17 18:44:55] LOG: connection received: host=172.18.0.5 port=45678
[2025-08-17 18:44:52] LOG: checkpoint complete: wrote 47 buffers
[2025-08-17 18:44:45] LOG: automatic vacuum of table completed
[2025-08-17 18:44:40] LOG: connection authorized: user=app_user database=production
...and 230 more entries

>>> CONTAINER: REGISTRY <<<
Log entries: 23
Status: Light activity
Recent activity:
[2025-08-17 17:30:15] INFO: GET /v2/autopar/manifests/latest 200
[2025-08-17 17:15:22] INFO: PUT /v2/afasask/blobs/upload 201
...and 21 more entries

>>> CONTAINER: PORTAINER <<<
Log entries: 45
Status: Administrative access
Recent activity:
[2025-08-17 16:20:10] INFO: User session created: admin
[2025-08-17 16:19:55] INFO: Container stats requested: all
...and 43 more entries

>>> CONTAINER: AFASASK <<<
Log entries: 0
Status: No recent logs (potentially concerning)

>>> CONTAINER: AFASASK-STAGING <<<
Log entries: 0
Status: No recent logs

>>> CONTAINER: AI-PRICE-CRAWLER-CRAWLER-1 <<<
Log entries: 89
Status: Error logs detected
Recent activity:
[2025-08-17 18:30:45] ERROR: Connection refused: target host unreachable
[2025-08-17 18:30:40] ERROR: Retry attempt 3/5 failed
[2025-08-17 18:30:35] WARN: Rate limit exceeded, backing off
[2025-08-17 18:30:30] ERROR: HTTP 429 Too Many Requests
...and 85 more entries (requires investigation)

>>> 11 OTHER CONTAINERS <<<
Combined entries: 0
Status: Silent (normal for background services)"""

    sections.append(create_section("Production Container Logs (Annotated)", container_logs))

    # Error Analysis
    error_analysis = """ERROR ANALYSIS SUMMARY:
Analysis period: 4 hours
Containers checked: 17
Containers with errors: 1
Total error entries: 23
Critical issues: 1

🔥 CRITICAL ISSUES:
• [ai-price-crawler-crawler-1] Connection refused: target host unreachable
  - Impact: Web crawling operations failing
  - Duration: Ongoing for 45 minutes
  - Recommended action: Check network connectivity and target endpoints

📊 ERROR BREAKDOWN BY CONTAINER:
• ai-price-crawler-crawler-1: 23 errors
  - Rate limiting: 12 occurrences
  - Connection timeouts: 8 occurrences
  - HTTP 429 errors: 3 occurrences
  Latest: "Retry attempt 3/5 failed"

⚠️  HEALTH WARNINGS:
• afasask: No logs in 4 hours (unusual silence)
• afasask-staging: No logs in 4 hours
• afasask-quick-chat: No logs in 4 hours
• 4 containers showing 'unhealthy' status in Docker

✅ HEALTHY CONTAINERS: 13/17
• metabase: Heavy activity, all operations normal
• postgres-container: Database operations stable
• registry: Light activity, no errors
• portainer: Administrative access logged"""

    sections.append(create_section("Error Analysis & Critical Issues", error_analysis))

    # System Metrics
    system_metrics = """PRODUCTION SERVER METRICS:

💾 DISK SPACE:
Filesystem      Size  Used Avail Use%
/dev/sda1       160G  89G   63G  59%  (Root filesystem)
/dev/sda2       500G  245G  230G  52%  (Docker volumes)
/dev/sda3       100G  23G   72G   24%  (Application data)

⚠️  Disk usage approaching 60% on root - monitor closely

🧠 MEMORY USAGE:
Total: 16GB
Used:  11.2GB (70%)
Free:  4.8GB (30%)
Buffers/Cache: 2.3GB

🔄 CPU USAGE:
Load average: 2.45 (5min), 2.78 (15min)
CPU cores: 8
Current usage: ~31% average

📈 SYSTEM UPTIME:
Up 25 days, 14:32
Last reboot: 2025-07-23 08:15

🌡️  SYSTEM HEALTH:
• Temperature: Normal
• Network: All interfaces up
• Services: All critical services running"""

    sections.append(create_section("System Resource Utilization", system_metrics))

    # Network Status
    network_status = """NETWORK & CONNECTIVITY STATUS:

🌐 EXTERNAL CONNECTIVITY:
• Internet: ✅ Active (ping google.com: 12ms)
• DNS Resolution: ✅ Working
• SSH Access: ✅ Authenticated connection established
• Docker Registry: ✅ Accessible

🔌 LISTENING SERVICES:
Port    Service              Status
22      SSH                  ✅ Active
80      HTTP (nginx)         ✅ Active
443     HTTPS (nginx)        ✅ Active
3101    autopar              ✅ Active
3102    afasask              ⚠️  Unhealthy
3103    autopar-staging      ✅ Active
3105    afasask-staging      ⚠️  Unhealthy
3106    afasask-quick-chat   ⚠️  Unhealthy
3120    aipc                 ✅ Active
3130    deplanbook           ✅ Active
3200    metabase             ✅ Active
5000    docker-registry      ✅ Active
5432    postgresql           ✅ Active
6333    qdrant               ✅ Active
7700    meilisearch          ✅ Active
9443    portainer            ✅ Active

🚨 CONNECTIVITY ISSUES:
• 3 services responding as unhealthy
• ai-price-crawler experiencing external connectivity issues
• May be related to upstream API rate limiting"""

    sections.append(create_section("Network & Connectivity Status", network_status))

    # Summary & Recommendations
    summary = f"""SYSTEM HEALTH SCORE: 78/100 (Good with concerns)

✅ STRENGTHS:
• Core infrastructure stable (database, web services)
• No critical security issues detected
• System resources within acceptable limits
• Monitoring and logging functioning correctly
• 13/17 containers operating normally

⚠️  AREAS OF CONCERN:
• 4 containers showing unhealthy status
• 1 container in restart loop (crawler)
• 3 application containers silent for 4+ hours
• Disk usage trending upward (59% on root)

🎯 IMMEDIATE ACTIONS REQUIRED:
1. Investigate ai-price-crawler-crawler-1 connectivity issues
2. Check afasask containers for application-level problems
3. Review unhealthy container configurations
4. Monitor disk usage trend

📋 RECOMMENDED FOLLOW-UP:
• Set up automated alerting for unhealthy containers
• Implement log rotation for high-volume containers
• Schedule disk cleanup maintenance
• Review crawler rate limiting configuration

📊 NEXT REPORT: Recommended in 4 hours or immediately if critical alerts trigger

Generated: {timestamp}
Report ID: MASTER-{datetime.now().strftime('%Y%m%d%H%M')}
Monitoring System: PitchAI Production Monitoring v2.0"""

    sections.append(create_section("Executive Summary & Recommendations", summary))

    # Generate final report
    full_report = "\\n".join(sections)

    # Save to file
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/demo_master_report_{timestamp_file}.txt"

    os.makedirs("reports", exist_ok=True)

    try:
        with open(filename, 'w') as f:
            f.write(full_report)

        print("✅ Demo Master Report Generated!")
        print(f"📁 File: {filename}")
        print(f"📏 Size: {len(full_report):,} characters")
        print(f"📊 Sections: {len(sections)}")
        print()
        print("🎯 This demonstrates the comprehensive monitoring capabilities:")
        print("   • Production container status with health indicators")
        print("   • Annotated logs organized by container")
        print("   • Error analysis with actionable insights")
        print("   • System metrics and resource utilization")
        print("   • Network connectivity assessment")
        print("   • Executive summary with recommendations")
        print()
        print("📋 The actual script will collect real data from:")
        print("   • Your 17 production containers via SSH")
        print("   • System metrics from the production server")
        print("   • Live application logs and error detection")

    except Exception as e:
        print(f"❌ Error saving demo report: {e}")

if __name__ == "__main__":
    main()
