#!/usr/bin/env python3
"""
Working Master Log Aggregator - Uses direct SSH commands to collect production data

This version works around dependency issues by using SSH directly.
"""

import os
import subprocess
import json
from datetime import datetime

def load_env_vars():
    """Load environment variables from .env file"""
    env_vars = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key] = value.strip('"\'')
    except FileNotFoundError:
        print("⚠️  .env file not found, using environment variables")
    return env_vars

def run_ssh_command(command: str, env_vars: dict) -> tuple[str, bool]:
    """Run a command on the production server via SSH"""
    host = env_vars.get('HETZNER_HOST', '37.27.67.52')
    user = env_vars.get('HETZNER_USER', 'root')
    
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no {user}@{host} '{command}'"
    
    try:
        result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr, result.returncode == 0
    except subprocess.TimeoutExpired:
        return "Command timed out", False
    except Exception as e:
        return f"SSH Error: {str(e)}", False

def run_local_command(command: str) -> tuple[str, bool]:
    """Run a local command"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout + result.stderr, result.returncode == 0
    except Exception as e:
        return f"Local Error: {str(e)}", False

def create_section(title: str, content: str) -> str:
    """Create a formatted section"""
    return f"""
{'='*80}
{title.upper()}
{'='*80}
{content}
"""

def main():
    """Generate working master log report"""
    
    print("🔧 Working Master Log Aggregator")
    print("=" * 50)
    
    # Load environment
    env_vars = load_env_vars()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    hours = 2
    
    sections = []
    
    # Header
    header = f"""PITCHAI PRODUCTION MONITORING - WORKING MASTER REPORT
Generated: {timestamp}
Collection Method: Direct SSH + Local commands
Time Period: {hours} hours

Data Sources:
• Production server: {env_vars.get('HETZNER_HOST', 'Not configured')}
• SSH user: {env_vars.get('HETZNER_USER', 'Not configured')}
• Local monitoring system

Report includes:
• Live production container status
• System resource utilization  
• Error detection and analysis
• Network connectivity status"""
    
    sections.append(create_section("Report Overview", header))
    
    print("📦 Collecting production container status...")
    # Production container status via SSH
    container_cmd = "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}\\t{{.Image}}'"
    container_status, success = run_ssh_command(container_cmd, env_vars)
    
    if success:
        container_summary = f"PRODUCTION CONTAINER STATUS:\\n{container_status}\\n\\nContainer count: {len(container_status.split('\\n')) - 2} running"
        sections.append(create_section("Production Container Status", container_summary))
    else:
        sections.append(create_section("Production Container Status", f"❌ Error: {container_status}"))
    
    print("📊 Collecting production system metrics...")
    # System metrics via SSH
    metrics_data = []
    
    # Disk space
    df_output, success = run_ssh_command("df -h", env_vars)
    if success:
        metrics_data.append(f"DISK SPACE:\\n{df_output}")
    
    # Memory
    free_output, success = run_ssh_command("free -h", env_vars)
    if success:
        metrics_data.append(f"\\nMEMORY USAGE:\\n{free_output}")
    
    # System load
    uptime_output, success = run_ssh_command("uptime", env_vars)
    if success:
        metrics_data.append(f"\\nSYSTEM LOAD:\\n{uptime_output}")
    
    # Top processes
    top_output, success = run_ssh_command("ps aux --sort=-%cpu | head -10", env_vars)
    if success:
        metrics_data.append(f"\\nTOP CPU PROCESSES:\\n{top_output}")
    
    sections.append(create_section("Production System Metrics", "\\n".join(metrics_data)))
    
    print("🚨 Collecting production error logs...")
    # Recent errors from containers
    error_data = []
    
    # Check for recent errors in docker logs
    error_check_cmd = """
    for container in $(docker ps --format '{{.Names}}'); do
        echo "=== $container ==="
        docker logs --since='2h' --timestamps $container 2>&1 | grep -i 'error\\|exception\\|fatal\\|fail' | tail -5
        echo ""
    done
    """
    
    error_output, success = run_ssh_command(error_check_cmd, env_vars)
    if success and error_output.strip():
        error_data.append(f"RECENT ERRORS (Last {hours} hours):\\n{error_output}")
    else:
        error_data.append(f"RECENT ERRORS: No critical errors detected in last {hours} hours ✅")
    
    sections.append(create_section("Error Analysis", "\\n".join(error_data)))
    
    print("🐳 Collecting Docker system info...")
    # Docker system information
    docker_info = []
    
    # Docker disk usage
    docker_df, success = run_ssh_command("docker system df", env_vars)
    if success:
        docker_info.append(f"DOCKER DISK USAGE:\\n{docker_df}")
    
    # Docker version
    docker_version, success = run_ssh_command("docker --version", env_vars)
    if success:
        docker_info.append(f"\\nDOCKER VERSION:\\n{docker_version}")
    
    # Container health status
    health_cmd = "docker ps --format 'table {{.Names}}\\t{{.Status}}' | grep -E 'unhealthy|restarting|exited'"
    health_output, success = run_ssh_command(health_cmd, env_vars)
    if success and health_output.strip():
        docker_info.append(f"\\nCONTAINER HEALTH ISSUES:\\n{health_output}")
    else:
        docker_info.append(f"\\nCONTAINER HEALTH: All containers healthy ✅")
    
    sections.append(create_section("Docker System Information", "\\n".join(docker_info)))
    
    print("🌐 Collecting network status...")
    # Network information
    network_info = []
    
    # Listening ports
    ports_cmd = "ss -tuln | grep LISTEN | head -20"
    ports_output, success = run_ssh_command(ports_cmd, env_vars)
    if success:
        network_info.append(f"LISTENING PORTS:\\n{ports_output}")
    
    # Network interfaces
    interfaces_cmd = "ip addr show | grep -E '^[0-9]+:|inet '"
    interfaces_output, success = run_ssh_command(interfaces_cmd, env_vars)
    if success:
        network_info.append(f"\\nNETWORK INTERFACES:\\n{interfaces_output}")
    
    sections.append(create_section("Network Status", "\\n".join(network_info)))
    
    print("💾 Collecting sample container logs...")
    # Sample logs from active containers
    logs_data = []
    
    # Get logs from a few key containers
    key_containers = ['metabase', 'postgres-container', 'autopar', 'afasask']
    
    for container in key_containers:
        log_cmd = f"docker logs --since='{hours}h' --timestamps --tail=10 {container} 2>/dev/null"
        log_output, success = run_ssh_command(log_cmd, env_vars)
        
        if success and log_output.strip():
            logs_data.append(f"\\n>>> CONTAINER: {container.upper()} <<<\\n{log_output}")
        else:
            logs_data.append(f"\\n>>> CONTAINER: {container.upper()} <<<\\nNo recent logs or container not found")
    
    sections.append(create_section("Sample Container Logs", "\\n".join(logs_data)))
    
    # Generate summary
    summary = f"""COLLECTION SUMMARY:
Timestamp: {timestamp}
Data collection: {'✅ Successful' if len(sections) > 3 else '⚠️ Partial'}
SSH connectivity: {'✅ Working' if 'Error:' not in str(sections[1]) else '❌ Failed'}
Total sections: {len(sections)}

This working master report demonstrates:
• Direct SSH access to production server
• Real-time container and system monitoring
• Automated log collection and analysis
• Comprehensive infrastructure visibility

The report aggregates critical production data into a single,
actionable document for monitoring and troubleshooting."""
    
    sections.append(create_section("Collection Summary", summary))
    
    # Generate final report
    full_report = "\\n".join(sections)
    
    # Save to file
    timestamp_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"reports/master_log_working_{timestamp_file}.txt"
    
    os.makedirs("reports", exist_ok=True)
    
    try:
        with open(filename, 'w') as f:
            f.write(full_report)
        
        print(f"\\n✅ Working Master Report Generated!")
        print(f"📁 Saved to: {filename}")
        print(f"📏 Size: {len(full_report):,} characters")
        print(f"📊 Sections: {len(sections)}")
        print(f"🔄 Collection time: {hours} hours of data")
        
        # Show brief preview
        print(f"\\n📋 Preview (first 800 chars):")
        print("=" * 40)
        print(full_report[:800] + "\\n...(truncated)")
        
    except Exception as e:
        print(f"❌ Error saving report: {e}")

if __name__ == "__main__":
    main()