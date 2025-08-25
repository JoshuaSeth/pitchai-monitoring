#!/usr/bin/env python3
"""
Simplified Master Log Aggregator - Works with existing production_logs CLI

This version uses the working CLI commands to collect data and formats it nicely.
"""

import os
import subprocess
import time
from datetime import datetime

def run_command(command: str, shell: bool = False) -> tuple[str, bool]:
    """Run a command and return output and success status"""
    try:
        if shell:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        else:
            result = subprocess.run(command.split(), capture_output=True, text=True, timeout=60)
        return result.stdout + result.stderr, result.returncode == 0
    except Exception as e:
        return f"Error: {str(e)}", False

def create_section(title: str, content: str) -> str:
    """Create a formatted section"""
    return f"""
{'='*80}
{title.upper()}
{'='*80}
{content}
"""

def main():
    """Generate master log report using CLI commands"""
    
    print("🚀 Simplified Master Log Aggregator")
    print("=" * 50)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    hours = 2  # Collect 2 hours of data
    
    sections = []
    
    # Header
    header = f"""PITCHAI PRODUCTION MONITORING - MASTER LOG REPORT
Generated: {timestamp}
Time Period: {hours} hours
Data Sources: Production containers + Local system

This comprehensive report includes:
• Production Docker container status (17 containers)
• Container logs with error analysis  
• Local system metrics
• Network information
• Overall system health"""
    
    sections.append(create_section("Master Report Header", header))
    
    print("📦 Collecting production container status...")
    # Production container status
    container_status, success = run_command("python3 -m monitoring.production_logs.cli status")
    if success:
        sections.append(create_section("Production Container Status", container_status))
    else:
        sections.append(create_section("Production Container Status", f"Error collecting data: {container_status}"))
    
    print("🏥 Checking production system health...")
    # Production health check
    health_check, success = run_command("python3 -m monitoring.production_logs.cli health")
    if success:
        sections.append(create_section("Production Health Check", health_check))
    else:
        sections.append(create_section("Production Health Check", f"Error: {health_check}"))
    
    print("🚨 Collecting production error analysis...")
    # Production errors
    error_check, success = run_command(f"python3 -m monitoring.production_logs.cli errors {hours}")
    if success:
        sections.append(create_section("Production Error Analysis", error_check))
    else:
        sections.append(create_section("Production Error Analysis", f"Error: {error_check}"))
    
    print("📋 Collecting recent production logs...")
    # Production logs (recent)
    recent_logs, success = run_command(f"python3 -m monitoring.production_logs.cli logs {hours}")
    if success:
        sections.append(create_section("Recent Production Logs", recent_logs))
    else:
        sections.append(create_section("Recent Production Logs", f"Error: {recent_logs}"))
    
    print("💾 Saving comprehensive logs to file...")
    # Save production logs to file
    save_result, success = run_command(f"python3 -m monitoring.production_logs.cli save {hours}")
    if success:
        sections.append(create_section("Log File Generation", save_result))
    else:
        sections.append(create_section("Log File Generation", f"Error: {save_result}"))
    
    print("📊 Collecting local system metrics...")
    # Local system info
    local_metrics = []
    
    # Disk space
    df_out, success = run_command("df -h")
    if success:
        local_metrics.append(f"DISK SPACE:\\n{df_out}")
    
    # System load  
    uptime_out, success = run_command("uptime")
    if success:
        local_metrics.append(f"\\nSYSTEM LOAD:\\n{uptime_out}")
    
    # Memory (try multiple commands for cross-platform)
    vm_stat_out, success = run_command("vm_stat")
    if success:
        local_metrics.append(f"\\nMEMORY STATS (macOS):\\n{vm_stat_out}")
    else:
        free_out, success = run_command("free -h")
        if success:
            local_metrics.append(f"\\nMEMORY USAGE:\\n{free_out}")
    
    # Top processes
    top_out, success = run_command("ps aux | head -20", shell=True)
    if success:
        local_metrics.append(f"\\nTOP PROCESSES:\\n{top_out}")
    
    sections.append(create_section("Local System Metrics", "\\n".join(local_metrics)))
    
    print("🌐 Collecting network information...")
    # Network info
    network_info = []
    
    # Network interfaces
    ifconfig_out, success = run_command("ifconfig")
    if success:
        network_info.append(f"NETWORK INTERFACES:\\n{ifconfig_out}")
    
    # Active connections
    netstat_out, success = run_command("netstat -an | head -30", shell=True)
    if success:
        network_info.append(f"\\nACTIVE CONNECTIONS:\\n{netstat_out}")
    
    sections.append(create_section("Network Information", "\\n".join(network_info)))
    
    # Generate final report
    full_report = "\\n".join(sections)
    
    # Add summary footer
    summary = f"""
{'='*80}
REPORT SUMMARY
{'='*80}
Report generated: {timestamp}
Total sections: {len(sections)}
Report size: {len(full_report):,} characters
Collection time: Complete

This master report provides comprehensive visibility into:
✅ Production Docker containers (remote via SSH)
✅ Application logs and error analysis  
✅ System health and metrics
✅ Network connectivity status
✅ Overall infrastructure status

For detailed analysis, review each section above.
Next steps: Archive this report and set up automated collection.
"""
    
    full_report += summary
    
    # Save to file
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/master_log_simple_{timestamp_file}.txt"
    
    os.makedirs("reports", exist_ok=True)
    
    try:
        with open(filename, 'w') as f:
            f.write(full_report)
        
        print(f"\\n✅ Master report generated successfully!")
        print(f"📁 Saved to: {filename}")
        print(f"📏 Size: {len(full_report):,} characters")
        print(f"📊 Sections: {len(sections)}")
        
        # Show preview
        print(f"\\n📋 Report Preview (first 1500 chars):")
        print("=" * 50)
        print(full_report[:1500] + "\\n...(truncated)")
        
    except Exception as e:
        print(f"❌ Error saving report: {e}")
        print("\\n📄 Report content:")
        print(full_report[:2000] + "\\n...(truncated)")

if __name__ == "__main__":
    main()