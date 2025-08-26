#!/usr/bin/env python3
"""
Master Log Aggregator for PitchAI Production Monitoring

This script collects comprehensive system and application data:
- Docker container logs with annotations
- System metrics (disk space, memory, CPU)
- Container health status
- Error summaries
- Production server statistics

All data is aggregated into a single, nicely formatted report.
"""

import os
import subprocess

# Add monitoring modules to path
import sys
import time
from datetime import datetime

sys.path.append('.')

def run_command(command: str, timeout: int = 30) -> tuple[str, str, int]:
    """Execute a command and return stdout, stderr, exit_code"""
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s", 1
    except Exception as e:
        return "", str(e), 1


class MasterLogAggregator:
    """Comprehensive log and system data aggregator for production monitoring."""

    def __init__(self, hours_back: int = 4):
        """Initialize the aggregator.

        Args:
            hours_back: How many hours of logs to collect (default: 4)
        """
        self.hours_back = hours_back
        self.timestamp = datetime.utcnow()
        self.report_sections = []

    def add_section(self, title: str, content: str, level: int = 1) -> None:
        """Add a formatted section to the report.

        Args:
            title: Section title
            content: Section content
            level: Header level (1=main, 2=sub, 3=detail)
        """
        separator_chars = {1: "=", 2: "-", 3: "."}
        separator = separator_chars.get(level, "-")

        section = f"""
{separator * 80}
{title.upper() if level == 1 else title}
{separator * 80}
{content}
"""
        self.report_sections.append(section)

    def collect_system_metrics(self) -> str:
        """Collect system-level metrics from the production server."""
        print("📊 Collecting system metrics...")

        metrics = []

        # Disk space
        print("  • Disk space...")
        df_out, df_err, df_code = run_command("df -h")
        if df_code == 0:
            metrics.append(f"DISK SPACE:\n{df_out}")
        else:
            metrics.append(f"DISK SPACE: Error - {df_err}")

        # Memory usage
        print("  • Memory usage...")
        free_out, free_err, free_code = run_command("free -h")
        if free_code == 0:
            metrics.append(f"\\nMEMORY USAGE:\n{free_out}")
        else:
            metrics.append(f"\\nMEMORY USAGE: Error - {free_err}")

        # CPU load
        print("  • CPU load...")
        uptime_out, uptime_err, uptime_code = run_command("uptime")
        if uptime_code == 0:
            metrics.append(f"\\nSYSTEM LOAD:\n{uptime_out}")
        else:
            metrics.append(f"\\nSYSTEM LOAD: Error - {uptime_err}")

        # Running processes
        print("  • Top processes...")
        ps_out, ps_err, ps_code = run_command("ps aux --sort=-%cpu")
        if ps_code == 0:
            # Get top 10 CPU-consuming processes
            lines = ps_out.split('\\n')
            top_processes = '\\n'.join(lines[:11])  # Header + top 10
            metrics.append(f"\\nTOP CPU PROCESSES:\n{top_processes}")
        else:
            metrics.append(f"\\nTOP CPU PROCESSES: Error - {ps_err}")

        return '\\n'.join(metrics)

    def collect_docker_status(self) -> str:
        """Collect Docker daemon and container status."""
        print("🐳 Collecting Docker status...")

        status_info = []

        # Docker system info
        docker_info_out, docker_info_err, docker_info_code = run_command("docker system df")
        if docker_info_code == 0:
            status_info.append(f"DOCKER DISK USAGE:\n{docker_info_out}")
        else:
            status_info.append(f"DOCKER DISK USAGE: Error - {docker_info_err}")

        # Docker version
        docker_version_out, docker_version_err, docker_version_code = run_command("docker --version")
        if docker_version_code == 0:
            status_info.append(f"\\nDOCKER VERSION:\n{docker_version_out}")

        # Running containers summary
        docker_ps_out, docker_ps_err, docker_ps_code = run_command("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'")
        if docker_ps_code == 0:
            status_info.append(f"\\nRUNNING CONTAINERS:\n{docker_ps_out}")
        else:
            status_info.append(f"\\nRUNNING CONTAINERS: Error - {docker_ps_err}")

        return '\\n'.join(status_info)

    def collect_production_logs(self) -> str:
        """Collect logs from production containers using the production_logs module."""
        print(f"📋 Collecting production logs (last {self.hours_back} hours)...")

        try:
            # Import the production logs module
            from monitoring.production_logs import LogInterface

            interface = LogInterface()

            # Get container list
            print("  • Getting container list...")
            containers = interface.get_containers()

            # Get all logs
            print(f"  • Collecting logs from {len(containers)} containers...")
            all_logs = interface.get_recent_logs(self.hours_back)

            # Format logs by container
            formatted_logs = []
            total_entries = 0

            for container_name in sorted(all_logs.keys()):
                logs = all_logs[container_name]
                total_entries += len(logs)

                if logs:
                    # Container header
                    formatted_logs.append(f"\\n>>> CONTAINER: {container_name.upper()} <<<")
                    formatted_logs.append(f"Log entries: {len(logs)}")
                    formatted_logs.append("-" * 60)

                    # Show recent logs (last 10 entries)
                    recent_logs = logs[-10:] if len(logs) > 10 else logs
                    for log_entry in recent_logs:
                        timestamp = log_entry['timestamp'][:19]  # Remove microseconds
                        level = log_entry.get('level', 'INFO')
                        message = log_entry['message']
                        formatted_logs.append(f"[{timestamp}] {level}: {message}")

                    if len(logs) > 10:
                        formatted_logs.append(f"... and {len(logs) - 10} more entries")

                else:
                    formatted_logs.append(f"\\n>>> CONTAINER: {container_name.upper()} <<<")
                    formatted_logs.append("No logs found in the specified time period")
                    formatted_logs.append("-" * 60)

            summary = f"PRODUCTION LOGS SUMMARY:\\nTotal containers: {len(containers)}\\nTotal log entries: {total_entries}\\nTime period: {self.hours_back} hours\\n\\n"
            return summary + '\\n'.join(formatted_logs)

        except Exception as e:
            return f"ERROR collecting production logs: {str(e)}"

    def collect_ui_test_results(self) -> str:
        """Run UI tests and collect results - prioritizing failures."""
        print("🎭 Running UI tests and collecting results...")

        try:
            import json
            import os
            import subprocess

            # Run Playwright tests
            print("  • Executing Playwright tests...")
            result = subprocess.run(
                ["npx", "playwright", "test", "--reporter=json"],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd="."
            )

            test_summary = []

            # Parse test results
            if result.returncode == 0:
                test_summary.append("✅ ALL UI TESTS PASSED!")
                test_summary.append("Test execution completed successfully.")
                test_summary.append(f"Exit code: {result.returncode}")

                # Still show some output for confirmation
                if result.stdout:
                    # Try to extract summary info
                    output_lines = result.stdout.split('\n')
                    for line in output_lines[-10:]:  # Last 10 lines often have summary
                        if any(word in line.lower() for word in ['passed', 'test', 'duration']):
                            test_summary.append(f"  {line.strip()}")

            else:
                # TESTS FAILED - This should definitely be included!
                test_summary.append("🚨 UI TESTS FAILED - CRITICAL ATTENTION NEEDED!")
                test_summary.append(f"Exit code: {result.returncode}")
                test_summary.append("")

                # Include both stdout and stderr for failed tests
                if result.stdout:
                    test_summary.append("STDOUT OUTPUT:")
                    stdout_lines = result.stdout.split('\n')
                    # Look for failures, errors, and summary
                    relevant_lines = []
                    for line in stdout_lines:
                        line_lower = line.lower()
                        if any(keyword in line_lower for keyword in ['fail', 'error', 'timeout', 'expect', '✓', '✗', 'passed']):
                            relevant_lines.append(f"  {line.strip()}")

                    if relevant_lines:
                        test_summary.extend(relevant_lines)
                    else:
                        # If no specific matches, show last 15 lines
                        test_summary.extend([f"  {line.strip()}" for line in stdout_lines[-15:] if line.strip()])

                if result.stderr:
                    test_summary.append("")
                    test_summary.append("STDERR OUTPUT:")
                    stderr_lines = result.stderr.split('\n')
                    test_summary.extend([f"  {line.strip()}" for line in stderr_lines if line.strip()])

            # Check for existing test result files
            reports_dir = "reports"
            if os.path.exists(reports_dir):
                test_files = [f for f in os.listdir(reports_dir) if f.startswith("test_results_") and f.endswith(".json")]
                if test_files:
                    latest_test_file = max(test_files, key=lambda x: os.path.getmtime(os.path.join(reports_dir, x)))
                    test_summary.append(f"\\nLatest test report: {latest_test_file}")

                    # Try to load and parse the latest results
                    try:
                        with open(os.path.join(reports_dir, latest_test_file)) as f:
                            test_data = json.load(f)

                        summary = test_data.get('summary', {})
                        test_summary.append(f"Report summary: {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed")

                        # If there were failures, show them prominently
                        if summary.get('failed', 0) > 0:
                            test_summary.append("\\n🚨 FAILED TEST DETAILS:")
                            for test_result in test_data.get('test_results', []):
                                if not test_result.get('success', True):
                                    test_name = test_result.get('test_name', 'Unknown')
                                    error = test_result.get('error', 'Unknown error')
                                    test_summary.append(f"  ❌ {test_name}")
                                    test_summary.append(f"     Error: {error[:200]}...")
                    except Exception as e:
                        test_summary.append(f"     Error reading test report: {e}")

            return '\\n'.join(test_summary)

        except subprocess.TimeoutExpired:
            return "🚨 UI TESTS TIMED OUT - CRITICAL ISSUE!\\nTests exceeded 5 minute timeout limit."
        except Exception as e:
            return f"🚨 ERROR RUNNING UI TESTS - CRITICAL ISSUE!\\nError: {str(e)}"

    def collect_error_summary(self) -> str:
        """Collect and format error summary from production."""
        print("🚨 Collecting error summary...")

        try:
            from monitoring.production_logs import LogInterface

            interface = LogInterface()
            error_summary = interface.get_error_summary(self.hours_back)

            summary_lines = [
                f"ERROR ANALYSIS (Last {self.hours_back} hours):",
                f"Containers checked: {error_summary['total_containers']}",
                f"Containers with errors: {error_summary['containers_with_errors']}",
                f"Total error entries: {error_summary['total_error_entries']}",
                f"Critical issues: {len(error_summary['critical_issues'])}"
            ]

            # Add critical issues details
            if error_summary['critical_issues']:
                summary_lines.append("\\nCRITICAL ISSUES:")
                for issue in error_summary['critical_issues']:
                    summary_lines.append(f"  • [{issue['container']}] {issue['message'][:100]}...")

            # Add error breakdown
            if error_summary['error_breakdown']:
                summary_lines.append("\\nERROR BREAKDOWN BY CONTAINER:")
                for container, details in error_summary['error_breakdown'].items():
                    summary_lines.append(f"  • {container}: {details['error_count']} errors")
                    if details['recent_errors']:
                        latest = details['recent_errors'][-1]
                        summary_lines.append(f"    Latest: {latest['message'][:80]}...")

            if error_summary['total_error_entries'] == 0:
                summary_lines.append("\\n✅ NO ERRORS DETECTED!")

            return '\\n'.join(summary_lines)

        except Exception as e:
            return f"ERROR collecting error summary: {str(e)}"

    def collect_network_info(self) -> str:
        """Collect network and connectivity information."""
        print("🌐 Collecting network information...")

        network_info = []

        # Network interfaces
        ip_out, ip_err, ip_code = run_command("ip addr show")
        if ip_code == 0:
            network_info.append(f"NETWORK INTERFACES:\n{ip_out}")
        else:
            # Fallback to ifconfig
            ifconfig_out, ifconfig_err, ifconfig_code = run_command("ifconfig")
            if ifconfig_code == 0:
                network_info.append(f"NETWORK INTERFACES:\n{ifconfig_out}")
            else:
                network_info.append(f"NETWORK INTERFACES: Error - {ip_err}")

        # Network connections
        ss_out, ss_err, ss_code = run_command("ss -tuln")
        if ss_code == 0:
            network_info.append(f"\\nLISTENING PORTS:\n{ss_out}")
        else:
            # Fallback to netstat
            netstat_out, netstat_err, netstat_code = run_command("netstat -tuln")
            if netstat_code == 0:
                network_info.append(f"\\nLISTENING PORTS:\n{netstat_out}")
            else:
                network_info.append(f"\\nLISTENING PORTS: Error - {ss_err}")

        return '\\n'.join(network_info)

    def generate_report_header(self) -> str:
        """Generate a comprehensive report header."""
        return f"""PITCHAI PRODUCTION MONITORING - MASTER LOG REPORT
Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
Time Period: {self.hours_back} hours
Report Type: Comprehensive System & Application Logs + UI Tests

This report contains:
• UI test results (CRITICAL: failures highlighted at top!)
• System metrics (disk, memory, CPU)
• Docker container status and logs
• Production application logs by container
• Error analysis and critical issues
• Network and connectivity information
• Overall system health assessment

NOTE: Failed UI tests are given priority placement in this report!"""

    def collect_all_data(self) -> str:
        """Collect all data and generate the master report."""
        print("🔄 Starting comprehensive data collection...")
        print(f"⏰ Collection period: {self.hours_back} hours")
        print()

        # Report header
        self.add_section("Master Log Report", self.generate_report_header(), level=1)

        # UI TEST RESULTS FIRST - Especially important if they fail!
        ui_test_results = self.collect_ui_test_results()
        # Use priority level based on test results
        test_level = 1 if "FAILED" in ui_test_results or "TIMED OUT" in ui_test_results or "ERROR" in ui_test_results else 2
        self.add_section("UI Test Results", ui_test_results, level=test_level)

        # System metrics
        system_metrics = self.collect_system_metrics()
        self.add_section("System Metrics", system_metrics, level=1)

        # Docker status
        docker_status = self.collect_docker_status()
        self.add_section("Docker Status", docker_status, level=1)

        # Production logs
        production_logs = self.collect_production_logs()
        self.add_section("Production Container Logs", production_logs, level=1)

        # Error summary
        error_summary = self.collect_error_summary()
        self.add_section("Error Analysis", error_summary, level=1)

        # Network info
        network_info = self.collect_network_info()
        self.add_section("Network Information", network_info, level=1)

        # Combine all sections
        full_report = '\\n'.join(self.report_sections)

        print()
        print("✅ Data collection complete!")
        print(f"📄 Report length: {len(full_report):,} characters")
        print(f"📊 Sections: {len(self.report_sections)}")

        # Alert if UI tests failed
        if "FAILED" in ui_test_results or "TIMED OUT" in ui_test_results:
            print("🚨 WARNING: UI TESTS FAILED - Check report for details!")

        return full_report

    def save_report(self, report: str, filename: str | None = None) -> str:
        """Save the report to a file.

        Args:
            report: The report content
            filename: Optional filename (auto-generated if not provided)

        Returns:
            Path to the saved file
        """
        if filename is None:
            timestamp = self.timestamp.strftime("%Y%m%d_%H%M%S")
            filename = f"master_log_report_{timestamp}.txt"

        # Ensure reports directory exists
        reports_dir = "reports"
        os.makedirs(reports_dir, exist_ok=True)

        filepath = os.path.join(reports_dir, filename)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"💾 Report saved to: {filepath}")
            print(f"📏 File size: {os.path.getsize(filepath):,} bytes")
            return filepath

        except Exception as e:
            print(f"❌ Failed to save report: {e}")
            return ""


def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(description="Master Log Aggregator for Production Monitoring")
    parser.add_argument("--hours", type=int, default=4, help="Hours of logs to collect (default: 4)")
    parser.add_argument("--save", action="store_true", help="Save report to file")
    parser.add_argument("--output", type=str, help="Output filename (optional)")
    parser.add_argument("--preview", action="store_true", help="Show preview of report sections")

    args = parser.parse_args()

    print("🚀 PitchAI Master Log Aggregator")
    print("=" * 50)
    print()

    # Create aggregator
    aggregator = MasterLogAggregator(hours_back=args.hours)

    # Collect all data
    start_time = time.time()
    report = aggregator.collect_all_data()
    collection_time = time.time() - start_time

    print(f"⏱️  Collection time: {collection_time:.1f} seconds")

    # Preview mode
    if args.preview:
        print("\\n" + "="*50)
        print("REPORT PREVIEW (first 1000 characters)")
        print("="*50)
        print(report[:1000] + "..." if len(report) > 1000 else report)
        print("\\n" + "="*50)
        print(f"Full report length: {len(report):,} characters")
        return

    # Save to file
    if args.save:
        filepath = aggregator.save_report(report, args.output)
        if filepath:
            print(f"\\n📁 Report available at: {filepath}")
    else:
        # Print to stdout
        print("\\n" + "="*50)
        print("FULL REPORT")
        print("="*50)
        print(report)


if __name__ == "__main__":
    main()
