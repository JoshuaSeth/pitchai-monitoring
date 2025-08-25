#!/usr/bin/env python3
"""CLI tool for production log access.

This script provides command-line access to production Docker container logs
with safe, read-only operations.

Usage:
    python -m monitoring.production_logs.cli status        # Show containers
    python -m monitoring.production_logs.cli logs          # Get recent logs (1 hour)
    python -m monitoring.production_logs.cli logs 4        # Get logs (4 hours)
    python -m monitoring.production_logs.cli errors        # Get recent errors
    python -m monitoring.production_logs.cli errors 6      # Get errors (6 hours)
    python -m monitoring.production_logs.cli container web-app 2  # Specific container
    python -m monitoring.production_logs.cli save 4        # Save logs to file
    python -m monitoring.production_logs.cli health        # Health check
"""

import sys
import json
from datetime import datetime
from typing import Optional

from .log_interface import LogInterface


def print_help():
    """Print help message."""
    print(__doc__)


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_help()
        return
    
    command = sys.argv[1].lower()
    
    try:
        interface = LogInterface()
        
        if command == "help" or command == "--help" or command == "-h":
            print_help()
            
        elif command == "status":
            print("🔍 Checking production server status...")
            interface.print_container_status()
            
        elif command == "health":
            print("🏥 Checking system health...")
            health = interface.collector.health_check()
            
            if health['status'] == 'healthy':
                print("✅ System is healthy")
                print(f"   SSH Connection: ✅")
                print(f"   Docker Access: ✅")
                print(f"   Containers Found: {health['container_count']}")
            else:
                print("❌ System is unhealthy")
                for error in health['errors']:
                    print(f"   Error: {error}")
            
        elif command == "logs":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            print(f"📋 Collecting logs from last {hours} hour{'s' if hours > 1 else ''}...")
            
            logs = interface.get_recent_logs(hours)
            total_entries = sum(len(container_logs) for container_logs in logs.values())
            
            print(f"Found {total_entries} log entries across {len(logs)} containers")
            print("\\nRecent logs:")
            print("=" * 60)
            
            for container_name, container_logs in logs.items():
                if container_logs:
                    print(f"\\n📦 {container_name} ({len(container_logs)} entries)")
                    # Show last 3 entries per container
                    for log_entry in container_logs[-3:]:
                        timestamp = log_entry['timestamp'][:19]  # Remove microseconds
                        level = log_entry.get('level', 'INFO')
                        message = log_entry['message'][:100]
                        print(f"   [{timestamp}] {level}: {message}{'...' if len(log_entry['message']) > 100 else ''}")
            
        elif command == "errors":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            print(f"🚨 Checking for errors in last {hours} hour{'s' if hours > 1 else ''}...")
            interface.print_recent_errors(hours)
            
        elif command == "container":
            if len(sys.argv) < 3:
                print("❌ Please specify a container name")
                print("Usage: python -m monitoring.production_logs.cli container <container_name> [hours]")
                return
            
            container_name = sys.argv[2]
            hours = int(sys.argv[3]) if len(sys.argv) > 3 else 1
            
            print(f"📦 Getting logs for container '{container_name}' (last {hours} hour{'s' if hours > 1 else ''})")
            
            logs = interface.get_logs(container_name, hours)
            print(f"Found {len(logs)} log entries")
            
            if logs:
                print("\\nRecent logs:")
                print("=" * 60)
                # Show last 10 entries
                for log_entry in logs[-10:]:
                    timestamp = log_entry['timestamp'][:19]
                    level = log_entry.get('level', 'INFO')
                    message = log_entry['message']
                    print(f"[{timestamp}] {level}: {message}")
            else:
                print("No logs found for this container in the specified time period")
                
        elif command == "save":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            print(f"💾 Saving logs from last {hours} hour{'s' if hours > 1 else ''} to file...")
            
            filepath = interface.save_all_logs(hours)
            print(f"✅ Logs saved to: {filepath}")
            
        elif command == "summary":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            print(f"📊 Generating summary for last {hours} hour{'s' if hours > 1 else ''}...")
            
            summary = interface.get_error_summary(hours)
            
            print(f"\\n📋 Production Summary")
            print("=" * 40)
            print(f"Analysis Period: {hours} hour{'s' if hours > 1 else ''}")
            print(f"Containers Monitored: {summary['total_containers']}")
            print(f"Containers with Errors: {summary['containers_with_errors']}")
            print(f"Total Error Entries: {summary['total_error_entries']}")
            print(f"Critical Issues: {len(summary['critical_issues'])}")
            
            if summary['critical_issues']:
                print("\\n🔥 Critical Issues:")
                for issue in summary['critical_issues']:
                    print(f"   [{issue['container']}] {issue['message'][:80]}...")
            
        else:
            print(f"❌ Unknown command: {command}")
            print("Available commands: status, health, logs, errors, container, save, summary")
            print("Use 'help' for detailed usage information")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()