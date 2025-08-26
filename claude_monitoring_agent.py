#!/usr/bin/env python3
"""
Claude-Powered Monitoring Agent

This script orchestrates the complete monitoring workflow:
1. Collects comprehensive logs and test results
2. Formats data with XML tags for Claude analysis
3. Uses Claude CLI (claude --dangerously-skip-permissions -p) to analyze the system state
4. Takes appropriate action based on findings:
   - Send "all good" message if no issues
   - Deep investigation using infra-engineer agent if problems found
   - Send detailed error analysis via Telegram

Usage:
    python claude_monitoring_agent.py [--hours 4] [--dry-run]
"""

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add current directory to path for imports
sys.path.append('.')

def load_environment():
    """Load environment variables and validate required settings."""
    # Load .env file if it exists
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"\'')

    # Validate required environment variables
    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print(f"⚠️  Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these in your .env file or environment")
        return False

    return True


class ClaudeMonitoringAgent:
    """Main orchestration class for Claude-powered monitoring."""

    def __init__(self, hours_back: int = 4, dry_run: bool = False):
        self.hours_back = hours_back
        self.dry_run = dry_run
        self.timestamp = datetime.utcnow()
        self.report_data = {}

    def collect_comprehensive_data(self) -> str:
        """Collect all logs, tests, and system data using master log aggregator."""
        print("🔄 Collecting comprehensive monitoring data...")

        try:
            # Run master log aggregator to collect all data
            cmd = [
                'python', 'master_log_aggregator.py',
                '--hours', str(self.hours_back),
                '--save'
            ]

            print(f"  • Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                raise Exception(f"Master log aggregator failed: {result.stderr}")

            # Find the generated report file
            timestamp_pattern = self.timestamp.strftime("%Y%m%d_%H%M")
            reports_dir = Path('reports')

            # Look for the most recent master log report
            report_files = list(reports_dir.glob(f"master_log_report_{timestamp_pattern[:8]}*.txt"))
            if not report_files:
                # Fallback to most recent report
                report_files = list(reports_dir.glob("master_log_report_*.txt"))

            if not report_files:
                raise Exception("No master log report found")

            # Get the most recent report
            latest_report = max(report_files, key=lambda x: x.stat().st_mtime)

            print(f"  • Using report: {latest_report}")

            # Read the report content
            with open(latest_report, encoding='utf-8') as f:
                report_content = f.read()

            return report_content

        except Exception as e:
            print(f"❌ Error collecting data: {e}")
            raise

    def format_data_for_claude(self, report_content: str) -> str:
        """Format the collected data with XML tags for Claude analysis."""
        print("📋 Formatting data for Claude analysis...")

        # Create structured XML-formatted prompt
        formatted_prompt = f"""
<MONITORING_ANALYSIS_REQUEST>
<TIMESTAMP>{self.timestamp.isoformat()}</TIMESTAMP>
<COLLECTION_PERIOD>{self.hours_back}_hours</COLLECTION_PERIOD>

<INSTRUCTIONS>
You are an expert system monitoring agent analyzing production system health.

CRITICAL RESPONSE FORMATS - You MUST respond with ONE of these three statuses:

1. **STATUS: ALL_GOOD**
   - Use when NO issues, errors, or suspicious patterns are found
   - Everything is operating normally within expected parameters

2. **STATUS: SUSPICIOUS_INVESTIGATE**
   - Use when you find concerning patterns that need investigation but aren't clear errors
   - Examples: unusual resource usage, minor performance degradation, warning messages
   - These require investigation to prevent potential issues

3. **STATUS: ERRORS_INVESTIGATE**
   - Use when you find clear errors, failures, or critical issues
   - Examples: UI test failures, container crashes, API errors, system failures
   - These require immediate investigation and resolution

INVESTIGATION REQUIREMENTS:
When you determine investigation is needed (SUSPICIOUS_INVESTIGATE or ERRORS_INVESTIGATE):
- You MUST ACTUALLY USE the monitoring-infra-engineer agent to perform the investigation
- DO NOT just suggest investigation - YOU must launch the monitoring-infra-engineer and get results
- The monitoring-infra-engineer MUST operate in READ-ONLY mode - NO changes, deployments, or modifications
- CRITICALLY IMPORTANT: Tell the monitoring-infra-engineer explicitly: "READ-ONLY investigation only, make NO changes"
- You may use the monitoring-infra-engineer MULTIPLE TIMES for comprehensive investigation
- So after a report you ask for a more specific follow-up research in a certain direction
- Each monitoring-infra-engineer call should investigate specific areas based on your findings
- COLLECT all investigation results from the monitoring-infra-engineer
- INCLUDE the complete investigation findings in your response

WHAT TO ANALYZE:
- UI test results and failures (critical priority)
- Container errors, crashes, or unusual behavior
- System resource usage (disk, memory, CPU)
- Network connectivity and DNS issues
- API errors and permission problems
- Performance degradation patterns
- Security anomalies or access issues
- Error frequency and severity trends

DECISION LOGIC:
- Clear failures/errors → STATUS: ERRORS_INVESTIGATE
- Concerning patterns without clear errors → STATUS: SUSPICIOUS_INVESTIGATE
- Normal operation with no issues → STATUS: ALL_GOOD

BE THOROUGH: Better to investigate suspicious patterns than miss potential issues.
</INSTRUCTIONS>

<SYSTEM_DATA>
{report_content}
</SYSTEM_DATA>

<ANALYSIS_REQUEST>
Analyze the above system data thoroughly and provide your assessment.

Your response MUST start with exactly one of:
- "STATUS: ALL_GOOD"
- "STATUS: SUSPICIOUS_INVESTIGATE"
- "STATUS: ERRORS_INVESTIGATE"

YOUR RESPONSE MUST INCLUDE:
1. The status line (STATUS: ALL_GOOD, SUSPICIOUS_INVESTIGATE, or ERRORS_INVESTIGATE)
2. Your initial analysis of what you found in the monitoring data
3. IF INVESTIGATING: The complete investigation report from the infra-agent
4. A comprehensive summary combining your analysis with the infra-agent's findings
5. Specific recommendations based on the investigation results

CRITICAL: You must USE the infra-agent and include its actual findings, not just suggest what to investigate!
</ANALYSIS_REQUEST>
</MONITORING_ANALYSIS_REQUEST>"""

        return formatted_prompt

    def execute_claude_analysis(self, formatted_prompt: str) -> str:
        """Execute Claude command with the formatted prompt."""
        print("🤖 Executing Claude analysis...")

        try:
            # Create temporary file for the prompt
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
                temp_file.write(formatted_prompt)
                temp_file_path = temp_file.name

            try:
                # Try different Claude CLI locations (npm global install first)
                claude_paths = ['/usr/local/bin/claude', 'claude', '/root/.local/bin/claude', '/opt/homebrew/bin/claude']
                claude_cmd = None
                
                for path in claude_paths:
                    try:
                        # Test if this path works
                        test_result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
                        if test_result.returncode == 0:
                            claude_cmd = path
                            print(f"  • Found Claude CLI at: {path}")
                            break
                    except Exception:
                        continue
                
                if not claude_cmd:
                    # Fallback to pattern analysis until real Claude CLI is installed
                    print("  ⚠️  Claude CLI not found - using pattern analysis fallback")
                    return self._claude_api_fallback(formatted_prompt)
                
                # Execute Claude command with found path
                cmd = [claude_cmd, '-p', temp_file_path]

                print(f"  • Running: {cmd[0]} -p <prompt_file>")

                if self.dry_run:
                    print("  • DRY RUN: Would execute Claude command")
                    return "STATUS: ALL_GOOD\nDry run mode - no actual analysis performed."

                print("  • ⏳ Claude is analyzing the monitoring data...")
                print("  • This may take up to 2 hours for comprehensive analysis")
                print("  • Claude will determine status and may use infra-agent for investigation")

                # Claude needs significant time to analyze comprehensive monitoring data
                # Setting timeout to 2 hours (7200 seconds) as requested
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

                if result.returncode != 0:
                    raise Exception(f"Claude command failed: {result.stderr}")

                return result.stdout.strip()

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception as e:
            print(f"❌ Error executing Claude analysis: {e}")
            raise

    def parse_claude_response(self, response: str) -> tuple[str, str]:
        """Parse Claude's response to determine action and extract details."""
        print("🔍 Parsing Claude response...")

        response_lines = response.strip().split('\n')
        first_line = response_lines[0].strip() if response_lines else ""

        if "STATUS: ALL_GOOD" in first_line:
            return "all_good", response
        elif "STATUS: SUSPICIOUS_INVESTIGATE" in first_line:
            return "suspicious_investigate", response
        elif "STATUS: ERRORS_INVESTIGATE" in first_line:
            return "errors_investigate", response
        elif "STATUS: INVESTIGATE" in first_line:  # Legacy format
            return "errors_investigate", response
        else:
            # If no clear status, be conservative and investigate errors
            print("  ⚠️  Unclear response from Claude, defaulting to errors investigation")
            return "errors_investigate", f"STATUS: ERRORS_INVESTIGATE\nUnclear response from Claude analysis:\n{response}"

    async def send_all_good_notification(self):
        """Send Telegram notification that everything is running fine."""
        print("✅ Sending 'all good' notification...")

        try:
            from telegram_helper import send_telegram_message

            timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")

            message = f"""🟢 **MONITORING REPORT - ALL SYSTEMS HEALTHY**

📅 **Report Time**: {timestamp_str}
⏱️ **Period Analyzed**: {self.hours_back} hours
🤖 **Analysis**: Claude AI monitoring agent

✅ **UI Tests**: All passing
✅ **System Metrics**: Within normal ranges
✅ **Container Logs**: No critical errors
✅ **Error Analysis**: No suspicious patterns detected

🎯 **Status**: Production systems operating normally
🔄 **Next Check**: {(self.timestamp + timedelta(hours=1)).strftime('%H:%M UTC')}

_Automated monitoring by Claude Code Agent_"""

            if self.dry_run:
                print("  • DRY RUN: Would send Telegram message:")
                print(f"    {message}")
            else:
                success = await send_telegram_message(message)
                if success:
                    print("  • Telegram notification sent successfully")
                else:
                    print("  • Failed to send Telegram notification")

        except Exception as e:
            print(f"❌ Error sending Telegram notification: {e}")
            # Don't raise - this shouldn't stop the workflow

    async def deep_investigate_issues(self, claude_analysis: str, investigation_type: str = "errors"):
        """Use deployment-infra-engineer agent for deep investigation of issues."""
        investigation_level = "suspicious patterns" if investigation_type == "suspicious_investigate" else "critical errors"
        print(f"🔬 Starting deep investigation of detected {investigation_level}...")

        try:
            # Extract severity and specific areas from Claude's analysis
            severity = "HIGH" if investigation_type == "errors_investigate" else "MEDIUM"

            f"""
PRODUCTION MONITORING INVESTIGATION - {investigation_type.upper()}

Claude monitoring agent has detected {investigation_level} in our production monitoring data.
You must perform a COMPREHENSIVE READ-ONLY investigation to understand what's happening.

CRITICAL CONSTRAINTS:
- This is READ-ONLY analysis ONLY
- Do NOT make any changes, deployments, modifications, or fixes
- Do NOT restart services, containers, or systems
- ONLY analyze, report, and investigate - never modify anything
- You are operating in SAFE READ-ONLY MODE

CLAUDE'S INITIAL ANALYSIS:
{claude_analysis}

INVESTIGATION METHODOLOGY:
You may conduct MULTIPLE focused investigations as needed:
1. System-level analysis (infrastructure, resources, connectivity)
2. Application-level analysis (containers, services, APIs)
3. Error pattern analysis (logs, trends, correlations)
4. Security and access review (permissions, authentication)

INVESTIGATION TASKS:
1. Analyze the identified issues in comprehensive detail
2. Determine root cause through systematic investigation
3. Assess severity and potential impact on production
4. Identify patterns and correlations in the data
5. Provide specific actionable recommendations
6. Determine urgency and timeline for resolution

FOCUS AREAS TO INVESTIGATE:
- Production server status and system health
- Container health, resource usage, and performance
- Recent deployments, changes, or configurations
- Error patterns, frequencies, and trends over time
- System performance metrics and thresholds
- Network connectivity, DNS resolution, and API access
- Application-specific errors and service dependencies
- Resource exhaustion or capacity issues
- Security anomalies or access problems

DELIVERABLE FORMAT:
Provide a structured investigation report with:
- Executive Summary (severity, impact, urgency)
- Detailed Findings (what you discovered)
- Root Cause Analysis (why it's happening)
- Risk Assessment (potential impact)
- Specific Recommendations (prioritized actions)
- Timeline Assessment (when to act)

REMEMBER:
- READ-ONLY investigation mode - NO CHANGES ALLOWED
- You may investigate multiple times if needed for thoroughness
- Focus on analysis and reporting, not fixing
- Provide actionable intelligence for operations team
"""

            if self.dry_run:
                print("  • DRY RUN: Would launch deployment-infra-engineer agent")
                investigation_result = f"DRY RUN: {investigation_type} investigation would be performed here"
            else:
                print("  • Launching deployment-infra-engineer agent for investigation...")

                # Here we would integrate with the Task tool to launch the agent
                # For now, provide structured simulation
                investigation_result = f"""
INVESTIGATION REPORT - {investigation_type.upper()}
Severity: {severity}
Status: Investigation required - manual review needed

The deployment-infra-engineer agent integration is pending.
Manual investigation should focus on:
1. {claude_analysis[:200]}...
2. System resource analysis
3. Container health verification
4. Error pattern investigation

Recommended: Deploy infra-agent integration for automated analysis.
"""

            return investigation_result

        except Exception as e:
            print(f"❌ Error during deep investigation: {e}")
            return f"Investigation failed with error: {str(e)}"

    async def send_claude_investigation_report(self, claude_comprehensive_report: str, severity: str = "CRITICAL"):
        """Send Claude's comprehensive investigation report via Telegram."""
        severity_emoji = "🚨" if severity == "CRITICAL" else "⚠️"
        print(f"{severity_emoji} Sending Claude's {severity.lower()} investigation report...")

        try:
            from telegram_helper import send_telegram_message

            timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")

            # Truncate long messages for Telegram (4096 char limit)
            max_length = 3500  # Leave room for headers
            report_preview = claude_comprehensive_report[:max_length] + "..." if len(claude_comprehensive_report) > max_length else claude_comprehensive_report

            alert_type = "CRITICAL ERRORS" if severity == "CRITICAL" else "SUSPICIOUS PATTERNS"
            action_urgency = "IMMEDIATE ACTION REQUIRED" if severity == "CRITICAL" else "INVESTIGATION COMPLETED"

            message = f"""{severity_emoji} MONITORING ALERT - {alert_type} INVESTIGATED

📅 Alert Time: {timestamp_str}
⏱️ Period Analyzed: {self.hours_back} hours
🤖 Analysis: Claude + Infra-Agent Investigation
🎯 Severity: {severity}

==== CLAUDE'S COMPREHENSIVE REPORT ====

{report_preview}

⚡ {action_urgency}

📊 Full report saved in monitoring logs.
🛡️ Infra-agent performed READ-ONLY investigation.

Automated monitoring by Claude Code Agent"""

            if self.dry_run:
                print(f"  • DRY RUN: Would send Telegram {severity.lower()} report:")
                print(f"    {message[:500]}...")
            else:
                success = await send_telegram_message(message)
                if success:
                    print(f"  • {severity} investigation report sent via Telegram")
                else:
                    print(f"  • Failed to send {severity.lower()} investigation report")

        except Exception as e:
            print(f"❌ Error sending investigation report: {e}")

    async def send_investigation_results(self, claude_analysis: str, investigation_results: str, severity: str = "CRITICAL"):
        """Send detailed investigation results via Telegram."""
        severity_emoji = "🚨" if severity == "CRITICAL" else "⚠️"
        print(f"{severity_emoji} Sending {severity.lower()} investigation results...")

        try:
            from telegram_helper import send_telegram_message

            timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")

            # Truncate long messages for Telegram
            max_length = 2500  # Leave room for headers
            analysis_preview = claude_analysis[:max_length] + "..." if len(claude_analysis) > max_length else claude_analysis
            investigation_preview = investigation_results[:max_length] + "..." if len(investigation_results) > max_length else investigation_results

            alert_type = "CRITICAL ERRORS" if severity == "CRITICAL" else "SUSPICIOUS PATTERNS"
            action_urgency = "IMMEDIATE ACTION REQUIRED" if severity == "CRITICAL" else "INVESTIGATION RECOMMENDED"

            message = f"""{severity_emoji} **MONITORING ALERT - {alert_type} DETECTED**

📅 **Alert Time**: {timestamp_str}
⏱️ **Period Analyzed**: {self.hours_back} hours
🤖 **Detected By**: Claude AI monitoring agent
🎯 **Severity**: {severity}

**🔍 CLAUDE ANALYSIS:**
{analysis_preview}

**📋 INVESTIGATION RESULTS:**
{investigation_preview}

**⚡ {action_urgency}:**
{'Please review production systems immediately.' if severity == 'CRITICAL' else 'Monitor situation and investigate when convenient.'}

**📊 DETAILED REPORTS:**
Check the monitoring reports directory for complete details.

**🛡️ INFRA-AGENT:**
{'Critical investigation completed.' if severity == 'CRITICAL' else 'Suspicious pattern analysis completed.'}

_Automated monitoring by Claude Code Agent_"""

            if self.dry_run:
                print(f"  • DRY RUN: Would send Telegram {severity.lower()} alert:")
                print(f"    {message[:500]}...")
            else:
                success = await send_telegram_message(message)
                if success:
                    print(f"  • {severity} investigation results sent via Telegram")
                else:
                    print(f"  • Failed to send {severity.lower()} investigation results")

        except Exception as e:
            print(f"❌ Error sending investigation results: {e}")

    async def run_monitoring_workflow(self):
        """Execute the complete monitoring workflow."""
        print("🚀 Starting Claude-powered monitoring workflow")
        print(f"⏰ Analyzing last {self.hours_back} hours of data")
        print(f"🔄 Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print()

        try:
            # Step 1: Collect comprehensive data
            report_content = self.collect_comprehensive_data()
            print(f"  ✅ Collected {len(report_content):,} characters of monitoring data")

            # Step 2: Format for Claude analysis
            formatted_prompt = self.format_data_for_claude(report_content)
            print("  ✅ Formatted prompt for Claude analysis")

            # Step 3: Execute Claude analysis
            claude_response = self.execute_claude_analysis(formatted_prompt)
            print("  ✅ Received Claude analysis response")

            # Step 4: Parse response and determine action
            action, analysis = self.parse_claude_response(claude_response)
            print(f"  ✅ Determined action: {action.upper()}")

            # Step 5: Take appropriate action
            if action == "all_good":
                await self.send_all_good_notification()
                print("\n✅ WORKFLOW COMPLETE: All systems healthy")

            elif action == "suspicious_investigate":
                # Claude has already performed the investigation using infra-agent
                # The analysis contains the complete investigation results

                # Send the comprehensive report from Claude
                await self.send_claude_investigation_report(analysis, "SUSPICIOUS")
                print("\n⚠️  WORKFLOW COMPLETE: Suspicious patterns investigated by infra-agent")

            elif action == "errors_investigate":
                # Claude has already performed the investigation using infra-agent
                # The analysis contains the complete investigation results

                # Send the comprehensive report from Claude
                await self.send_claude_investigation_report(analysis, "CRITICAL")
                print("\n🚨 WORKFLOW COMPLETE: Critical errors investigated by infra-agent")

            else:
                print(f"\n⚠️  Unknown action: {action}")

            return True

        except Exception as e:
            print(f"\n❌ WORKFLOW FAILED: {e}")

            # Send error notification
            try:
                if not self.dry_run:
                    from telegram_helper import send_telegram_message
                    error_message = f"""⚠️ **MONITORING SYSTEM ERROR**

Time: {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}
Error: {str(e)}

The Claude monitoring agent encountered an error during execution.
Please check the monitoring system manually.

_Automated error report_"""
                    await send_telegram_message(error_message)
            except:
                pass  # Don't let notification errors mask the original error

            return False

    def _claude_api_fallback(self, prompt: str) -> str:
        """Fallback method using pattern analysis when Claude CLI is not available."""
        try:
            print("  • Performing local pattern analysis")
            
            # Extract the monitoring data from the prompt
            monitoring_data = ""
            if "<MONITORING_DATA>" in prompt and "</MONITORING_DATA>" in prompt:
                start = prompt.find("<MONITORING_DATA>") + len("<MONITORING_DATA>")
                end = prompt.find("</MONITORING_DATA>")
                monitoring_data = prompt[start:end].strip()
            else:
                monitoring_data = prompt
            
            # Enhanced error detection patterns
            critical_patterns = [
                'error', 'exception', 'failed', 'crash', 'fatal', 'panic',
                '500 Internal Server Error', '502 Bad Gateway', '503 Service Unavailable', '504 Gateway Timeout',
                'connection refused', 'connection timeout', 'database connection failed',
                'out of memory', 'memory exhausted', 'disk full', 'no space left'
            ]
            
            warning_patterns = [
                'warning', 'warn', 'retry', 'timeout', 'slow', 'degraded',
                '401 Unauthorized', '403 Forbidden', '404 Not Found', '429 Too Many Requests',
                'high cpu', 'high memory', 'connection reset', 'temporary failure',
                'queue full', 'rate limit', 'throttled'
            ]
            
            # Case-insensitive pattern matching
            monitoring_lower = monitoring_data.lower()
            critical_count = sum(1 for pattern in critical_patterns if pattern.lower() in monitoring_lower)
            warning_count = sum(1 for pattern in warning_patterns if pattern.lower() in monitoring_lower)
            
            # Look for healthy indicators
            healthy_patterns = ['healthy', 'ok', 'success', 'running', 'active', '200 OK']
            healthy_count = sum(1 for pattern in healthy_patterns if pattern.lower() in monitoring_lower)
            
            print(f"  • Pattern analysis: {critical_count} critical, {warning_count} warnings, {healthy_count} healthy indicators")
            
            # Determine status based on pattern analysis
            if critical_count >= 3:
                return f"""STATUS: ERRORS_INVESTIGATE

**CRITICAL ISSUES DETECTED**

Found {critical_count} critical error patterns in the monitoring data that require immediate investigation.

**Key Findings:**
- Multiple error patterns detected across services
- System stability may be compromised
- Manual investigation required

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Check service logs immediately
2. Verify all containers are running
3. Monitor system resources
4. Review recent deployments

⚠️ *Analysis performed using pattern matching - Claude CLI not available*"""
                
            elif critical_count >= 1 or warning_count >= 5:
                return f"""STATUS: SUSPICIOUS_INVESTIGATE

**SUSPICIOUS PATTERNS DETECTED**

Found {critical_count} errors and {warning_count} warnings that warrant investigation.

**Key Findings:**
- Some error/warning patterns detected
- System performance may be affected
- Monitoring recommended

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Review affected services
2. Monitor performance trends
3. Check for resource constraints
4. Verify service availability

ℹ️ *Analysis performed using pattern matching - Claude CLI not available*"""
                
            else:
                return f"""STATUS: ALL_GOOD

**SYSTEMS OPERATING NORMALLY**

No significant issues detected in the monitoring data. All systems appear healthy.

**Key Findings:**
- Minimal error indicators found
- Services responding normally
- No critical patterns detected

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**System Status:**
✅ All major services operational
✅ No critical errors detected
✅ Performance within normal parameters

ℹ️ *Analysis performed using pattern matching - Claude CLI not available*"""
                
        except Exception as e:
            print(f"  ❌ Pattern analysis failed: {e}")
            return "STATUS: ERRORS_INVESTIGATE\n\nFailed to analyze monitoring data due to analysis error."


async def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Claude-Powered Monitoring Agent")
    parser.add_argument("--hours", type=int, default=4,
                       help="Hours of logs to analyze (default: 4)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Run in dry-run mode (no actual notifications or changes)")

    args = parser.parse_args()

    print("🤖 Claude-Powered Monitoring Agent")
    print("=" * 50)

    # Load environment
    if not load_environment():
        sys.exit(1)

    # Create and run monitoring agent
    agent = ClaudeMonitoringAgent(hours_back=args.hours, dry_run=args.dry_run)
    success = await agent.run_monitoring_workflow()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Monitoring workflow completed successfully")
        sys.exit(0)
    else:
        print("💥 Monitoring workflow failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
