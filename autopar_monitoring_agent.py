#!/usr/bin/env python3
"""
Autopar Staging Monitoring Agent

This script monitors the staging.autopar.pitchai.net website and its associated
Docker containers (autopar-redis, autopar-rabbitmq) with the same comprehensive
approach as the main production monitoring system.

Runs on the same schedule as the main monitoring agent and provides:
1. Website health monitoring for staging.autopar.pitchai.net  
2. Container-specific log analysis for autopar containers
3. Claude AI-powered analysis and alerts
4. Telegram notifications for autopar-specific issues

Usage:
    python autopar_monitoring_agent.py [--hours 4] [--dry-run]
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


class AutoparMonitoringAgent:
    """Specialized monitoring agent for Autopar staging environment."""

    def __init__(self, hours_back: int = 4, dry_run: bool = False):
        self.hours_back = hours_back
        self.dry_run = dry_run
        self.timestamp = datetime.utcnow()
        self.autopar_containers = ['autopar-redis', 'autopar-rabbitmq']
        self.staging_url = 'https://staging.autopar.pitchai.net'

    def collect_autopar_data(self) -> str:
        """Collect comprehensive autopar-specific monitoring data."""
        print("🔄 Collecting Autopar staging monitoring data...")

        data_sections = []

        # Website health check
        website_status = self.check_website_health()
        data_sections.append(f"AUTOPAR WEBSITE HEALTH:\n{website_status}")

        # Container status and logs
        container_status = self.collect_container_status()
        data_sections.append(f"AUTOPAR CONTAINER STATUS:\n{container_status}")

        # Detailed container logs
        container_logs = self.collect_container_logs()
        data_sections.append(f"AUTOPAR CONTAINER LOGS:\n{container_logs}")

        # System metrics for autopar containers
        container_metrics = self.collect_container_metrics()
        data_sections.append(f"AUTOPAR CONTAINER METRICS:\n{container_metrics}")

        # Error analysis
        error_analysis = self.analyze_autopar_errors()
        data_sections.append(f"AUTOPAR ERROR ANALYSIS:\n{error_analysis}")

        full_report = "\n" + "="*80 + "\n".join(data_sections)
        print(f"  ✅ Collected {len(full_report):,} characters of autopar monitoring data")
        
        return full_report

    def check_website_health(self) -> str:
        """Check staging.autopar.pitchai.net website health."""
        print("  • Checking staging.autopar.pitchai.net health...")
        
        health_info = []
        
        try:
            # Basic connectivity check
            result = subprocess.run([
                'curl', '-I', '-s', '--max-time', '10', self.staging_url
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                health_info.append(f"✅ Website accessible: {self.staging_url}")
                health_info.append(f"HTTP Response Headers:\n{result.stdout}")
            else:
                health_info.append(f"❌ Website inaccessible: {self.staging_url}")
                health_info.append(f"Error: {result.stderr}")

            # Try to get content
            content_result = subprocess.run([
                'curl', '-s', '--max-time', '10', self.staging_url
            ], capture_output=True, text=True, timeout=15)
            
            if content_result.returncode == 0 and content_result.stdout:
                content_length = len(content_result.stdout)
                health_info.append(f"✅ Content received: {content_length} bytes")
                
                # Check for common error indicators in content
                content_lower = content_result.stdout.lower()
                if 'error' in content_lower or '404' in content_lower or '500' in content_lower:
                    health_info.append("⚠️  Warning: Error indicators found in page content")
                    health_info.append(f"Content preview: {content_result.stdout[:200]}...")
                else:
                    health_info.append("✅ Content appears healthy")
            else:
                health_info.append("⚠️  No content received from website")

            # Check common API endpoints
            for endpoint in ['/health', '/api/health', '/status']:
                endpoint_url = f"{self.staging_url}{endpoint}"
                endpoint_result = subprocess.run([
                    'curl', '-s', '--max-time', '5', endpoint_url
                ], capture_output=True, text=True, timeout=10)
                
                if endpoint_result.returncode == 0 and endpoint_result.stdout:
                    health_info.append(f"✅ Endpoint {endpoint}: {endpoint_result.stdout[:100]}")

        except Exception as e:
            health_info.append(f"❌ Error checking website health: {str(e)}")

        return '\n'.join(health_info)

    def collect_container_status(self) -> str:
        """Collect status of autopar containers."""
        print("  • Collecting autopar container status...")
        
        status_info = []
        
        try:
            # Check if containers are running
            for container in self.autopar_containers:
                result = subprocess.run([
                    'docker', 'ps', '--filter', f'name={container}', 
                    '--format', 'table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}'
                ], capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    if container in result.stdout:
                        status_info.append(f"✅ {container} container status:")
                        status_info.append(f"   {result.stdout}")
                    else:
                        status_info.append(f"❌ {container} container not running")
                else:
                    status_info.append(f"❌ Error checking {container}: {result.stderr}")

            # Get container resource usage
            for container in self.autopar_containers:
                stats_result = subprocess.run([
                    'docker', 'stats', '--no-stream', '--format', 
                    'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}', container
                ], capture_output=True, text=True, timeout=15)
                
                if stats_result.returncode == 0:
                    status_info.append(f"📊 {container} resource usage:")
                    status_info.append(f"   {stats_result.stdout}")

        except Exception as e:
            status_info.append(f"❌ Error collecting container status: {str(e)}")

        return '\n'.join(status_info)

    def collect_container_logs(self) -> str:
        """Collect detailed logs from autopar containers."""
        print("  • Collecting autopar container logs...")
        
        logs_info = []
        since_time = datetime.utcnow() - timedelta(hours=self.hours_back)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
        
        for container in self.autopar_containers:
            try:
                print(f"    - Getting logs for {container}...")
                
                # Get recent logs with timestamps
                result = subprocess.run([
                    'docker', 'logs', '--timestamps', '--since', since_str, 
                    '--tail', '100', container
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    logs_info.append(f"📋 {container.upper()} LOGS (last {self.hours_back} hours):")
                    logs_info.append("=" * 60)
                    
                    if result.stdout:
                        logs_info.append(result.stdout)
                    else:
                        logs_info.append("No stdout logs found")
                    
                    if result.stderr:
                        logs_info.append(f"\nSTDERR for {container}:")
                        logs_info.append(result.stderr)
                        
                    logs_info.append("")
                else:
                    logs_info.append(f"❌ Error getting logs for {container}: {result.stderr}")

            except Exception as e:
                logs_info.append(f"❌ Exception getting logs for {container}: {str(e)}")

        return '\n'.join(logs_info)

    def collect_container_metrics(self) -> str:
        """Collect detailed metrics for autopar containers."""
        print("  • Collecting autopar container metrics...")
        
        metrics_info = []
        
        try:
            # Docker system df for autopar containers
            result = subprocess.run([
                'docker', 'system', 'df'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                metrics_info.append("DOCKER SYSTEM USAGE:")
                metrics_info.append(result.stdout)

            # Inspect each container for detailed info
            for container in self.autopar_containers:
                inspect_result = subprocess.run([
                    'docker', 'inspect', container
                ], capture_output=True, text=True, timeout=10)
                
                if inspect_result.returncode == 0:
                    import json
                    try:
                        inspect_data = json.loads(inspect_result.stdout)[0]
                        state = inspect_data.get('State', {})
                        
                        metrics_info.append(f"\n{container.upper()} DETAILED INFO:")
                        metrics_info.append(f"Status: {state.get('Status', 'unknown')}")
                        metrics_info.append(f"Running: {state.get('Running', False)}")
                        metrics_info.append(f"Started: {state.get('StartedAt', 'unknown')}")
                        metrics_info.append(f"Restart Count: {state.get('RestartCount', 0)}")
                        
                        if state.get('Health'):
                            health = state['Health']
                            metrics_info.append(f"Health Status: {health.get('Status', 'unknown')}")
                            
                    except json.JSONDecodeError:
                        metrics_info.append(f"Error parsing inspect data for {container}")

        except Exception as e:
            metrics_info.append(f"❌ Error collecting container metrics: {str(e)}")

        return '\n'.join(metrics_info)

    def analyze_autopar_errors(self) -> str:
        """Analyze errors specific to autopar containers and website."""
        print("  • Analyzing autopar-specific errors...")
        
        error_analysis = []
        error_count = 0
        warning_count = 0
        
        # Error patterns specific to autopar/redis/rabbitmq
        autopar_error_patterns = [
            'error', 'exception', 'failed', 'timeout', 'connection refused',
            'memory_high_watermark', 'disk_free_limit', 'queue full',
            'authentication failed', 'permission denied', 'broken pipe',
            'redis error', 'rabbitmq error', 'amqp error'
        ]
        
        warning_patterns = [
            'warning', 'alarm_handler', 'retry', 'reconnect', 'degraded'
        ]
        
        # Analyze logs from each container
        since_time = datetime.utcnow() - timedelta(hours=self.hours_back)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
        
        for container in self.autopar_containers:
            try:
                result = subprocess.run([
                    'docker', 'logs', '--since', since_str, container
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    logs = (result.stdout + '\n' + result.stderr).lower()
                    
                    container_errors = []
                    container_warnings = []
                    
                    for line in logs.split('\n'):
                        line_lower = line.lower()
                        
                        # Check for error patterns
                        for pattern in autopar_error_patterns:
                            if pattern in line_lower:
                                container_errors.append(line.strip())
                                error_count += 1
                                break
                        
                        # Check for warning patterns
                        for pattern in warning_patterns:
                            if pattern in line_lower:
                                container_warnings.append(line.strip())
                                warning_count += 1
                                break
                    
                    if container_errors:
                        error_analysis.append(f"\n🚨 ERRORS in {container}:")
                        for error in container_errors[-5:]:  # Last 5 errors
                            error_analysis.append(f"  • {error}")
                    
                    if container_warnings:
                        error_analysis.append(f"\n⚠️  WARNINGS in {container}:")
                        for warning in container_warnings[-3:]:  # Last 3 warnings
                            error_analysis.append(f"  • {warning}")

            except Exception as e:
                error_analysis.append(f"❌ Error analyzing {container}: {str(e)}")

        # Summary
        error_analysis.insert(0, f"ERROR SUMMARY (last {self.hours_back} hours):")
        error_analysis.insert(1, f"Total Errors: {error_count}")
        error_analysis.insert(2, f"Total Warnings: {warning_count}")
        error_analysis.insert(3, f"Containers Analyzed: {len(self.autopar_containers)}")

        if error_count == 0 and warning_count == 0:
            error_analysis.append("\n✅ NO ERRORS OR WARNINGS DETECTED in Autopar containers!")

        return '\n'.join(error_analysis)

    def format_data_for_claude(self, autopar_data: str) -> str:
        """Format autopar monitoring data for Claude analysis."""
        print("📋 Formatting autopar data for Claude analysis...")

        formatted_prompt = f"""
<AUTOPAR_MONITORING_ANALYSIS_REQUEST>
<TIMESTAMP>{self.timestamp.isoformat()}</TIMESTAMP>
<COLLECTION_PERIOD>{self.hours_back}_hours</COLLECTION_PERIOD>
<FOCUS>AUTOPAR_STAGING_ENVIRONMENT</FOCUS>

<INSTRUCTIONS>
You are an expert system monitoring agent analyzing the AUTOPAR STAGING environment.

FOCUS AREAS:
- staging.autopar.pitchai.net website health and accessibility
- autopar-redis container (Redis database service)
- autopar-rabbitmq container (RabbitMQ message broker)
- Container-specific error patterns and performance issues
- Application-level health indicators

CRITICAL RESPONSE FORMATS - You MUST respond with ONE of these three statuses:

1. **STATUS: ALL_GOOD**
   - Use when autopar website is accessible and containers are healthy
   - No errors, crashes, or suspicious patterns in autopar services

2. **STATUS: SUSPICIOUS_INVESTIGATE**
   - Use when you find concerning patterns in autopar services
   - Examples: memory warnings in RabbitMQ, slow website responses, minor Redis issues
   - These require investigation to prevent autopar service degradation

3. **STATUS: ERRORS_INVESTIGATE**
   - Use when you find clear autopar service failures or critical issues
   - Examples: website down, container crashes, authentication failures, connection errors
   - These require immediate investigation and resolution

AUTOPAR-SPECIFIC ANALYSIS:
- Website Response: Check HTTP status, response times, content errors
- Redis Health: Monitor memory usage, connection counts, persistence
- RabbitMQ Health: Check memory watermarks, queue status, connection issues
- Container Stability: Monitor restarts, resource usage, error patterns
- Service Dependencies: Analyze inter-service communication issues

INVESTIGATION REQUIREMENTS:
When you determine investigation is needed (SUSPICIOUS_INVESTIGATE or ERRORS_INVESTIGATE):
- You MUST ACTUALLY USE the monitoring-infra-engineer agent for investigation
- Focus specifically on autopar staging environment issues
- The monitoring-infra-engineer MUST operate in READ-ONLY mode - NO changes
- Tell the monitoring-infra-engineer: "READ-ONLY investigation of AUTOPAR STAGING only"
- Collect investigation results and include them in your response

DECISION LOGIC FOR AUTOPAR:
- Website down or containers crashed → STATUS: ERRORS_INVESTIGATE
- Memory warnings, slow responses, minor errors → STATUS: SUSPICIOUS_INVESTIGATE  
- All services healthy and responsive → STATUS: ALL_GOOD
</INSTRUCTIONS>

<AUTOPAR_SYSTEM_DATA>
{autopar_data}
</AUTOPAR_SYSTEM_DATA>

<ANALYSIS_REQUEST>
Analyze the above AUTOPAR STAGING data thoroughly and provide your assessment.

Your response MUST start with exactly one of:
- "STATUS: ALL_GOOD"
- "STATUS: SUSPICIOUS_INVESTIGATE" 
- "STATUS: ERRORS_INVESTIGATE"

YOUR RESPONSE MUST INCLUDE:
1. The status line for AUTOPAR staging environment
2. Your analysis of autopar website and container health
3. IF INVESTIGATING: Complete investigation report from the infra-agent
4. Autopar-specific recommendations and findings
5. Summary focused on autopar staging service health

CRITICAL: Focus on AUTOPAR STAGING environment only - investigate autopar-specific issues!
</ANALYSIS_REQUEST>
</AUTOPAR_MONITORING_ANALYSIS_REQUEST>"""

        return formatted_prompt

    def execute_claude_analysis(self, formatted_prompt: str) -> str:
        """Execute Claude command with autopar monitoring data."""
        print("🤖 Executing Claude analysis for Autopar staging...")

        try:
            # Create temporary file for the prompt
            import uuid
            temp_file_path = f"autopar_claude_prompt_{uuid.uuid4().hex[:8]}.txt"
            with open(temp_file_path, 'w') as temp_file:
                temp_file.write(formatted_prompt)

            try:
                # Try different Claude CLI locations
                claude_paths = ['/usr/local/bin/claude', 'claude', '/root/.local/bin/claude', '/opt/homebrew/bin/claude']
                claude_cmd = None
                
                for path in claude_paths:
                    try:
                        test_result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
                        if test_result.returncode == 0:
                            claude_cmd = path
                            print(f"  • Found Claude CLI at: {path}")
                            break
                    except Exception:
                        continue
                
                if not claude_cmd:
                    print("  ⚠️  Claude CLI not found - using pattern analysis fallback")
                    return self._autopar_pattern_analysis(formatted_prompt)
                
                # Execute Claude command
                cmd = [claude_cmd, '-p', temp_file_path]
                print(f"  • Running: {cmd[0]} -p <autopar_prompt_file>")

                if self.dry_run:
                    print("  • DRY RUN: Would execute Claude command for autopar analysis")
                    return "STATUS: ALL_GOOD\nDry run mode - no actual autopar analysis performed."

                print("  • ⏳ Claude is analyzing autopar staging environment...")
                print("  • This may take time for comprehensive autopar analysis")

                # Claude analysis with timeout
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

                if result.returncode != 0:
                    raise Exception(f"Claude command failed: {result.stderr}")

                return result.stdout.strip()

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception as e:
            print(f"❌ Error executing Claude analysis for autopar: {e}")
            raise

    def _autopar_pattern_analysis(self, prompt: str) -> str:
        """Fallback pattern analysis for autopar when Claude CLI unavailable."""
        print("  • Performing autopar pattern analysis...")
        
        # Extract monitoring data
        if "<AUTOPAR_SYSTEM_DATA>" in prompt:
            start = prompt.find("<AUTOPAR_SYSTEM_DATA>") + len("<AUTOPAR_SYSTEM_DATA>")
            end = prompt.find("</AUTOPAR_SYSTEM_DATA>")
            monitoring_data = prompt[start:end].strip().lower()
        else:
            monitoring_data = prompt.lower()

        # Autopar-specific error patterns
        critical_patterns = [
            'website inaccessible', 'container not running', 'connection refused',
            'authentication failed', 'redis error', 'rabbitmq error', 'crashed',
            'exited', 'unhealthy', 'failed', 'exception'
        ]
        
        warning_patterns = [
            'memory_high_watermark', 'alarm_handler', 'warning', 'retry',
            'slow', 'timeout', 'degraded', 'high cpu', 'high memory'
        ]
        
        healthy_patterns = [
            'website accessible', 'container status', 'healthy', 'running',
            'background saving terminated with success', 'authenticated and granted access'
        ]

        critical_count = sum(1 for pattern in critical_patterns if pattern in monitoring_data)
        warning_count = sum(1 for pattern in warning_patterns if pattern in monitoring_data)
        healthy_count = sum(1 for pattern in healthy_patterns if pattern in monitoring_data)

        print(f"  • Autopar pattern analysis: {critical_count} critical, {warning_count} warnings, {healthy_count} healthy")

        if critical_count >= 2:
            return f"""STATUS: ERRORS_INVESTIGATE

**CRITICAL AUTOPAR STAGING ISSUES DETECTED**

Found {critical_count} critical patterns in autopar staging monitoring data.

**Key Findings:**
- Autopar staging environment has critical issues
- Multiple error patterns detected in containers or website
- Immediate investigation required for staging.autopar.pitchai.net

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}  
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Check staging.autopar.pitchai.net accessibility immediately
2. Verify autopar-redis and autopar-rabbitmq container health
3. Review autopar container logs for critical errors
4. Monitor autopar service dependencies

⚠️ *Analysis performed using autopar pattern matching - Claude CLI not available*"""
            
        elif critical_count >= 1 or warning_count >= 3:
            return f"""STATUS: SUSPICIOUS_INVESTIGATE

**SUSPICIOUS AUTOPAR STAGING PATTERNS DETECTED**

Found {critical_count} errors and {warning_count} warnings in autopar staging environment.

**Key Findings:**
- Some autopar-specific warning patterns detected
- Staging environment may have performance issues
- Monitoring recommended for autopar services

**Pattern Analysis Summary:**  
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Monitor staging.autopar.pitchai.net response times
2. Check autopar container resource usage
3. Review RabbitMQ memory watermark warnings
4. Verify Redis persistence and connections

ℹ️ *Analysis performed using autopar pattern matching - Claude CLI not available*"""
            
        else:
            return f"""STATUS: ALL_GOOD

**AUTOPAR STAGING SYSTEMS OPERATING NORMALLY**

No significant issues detected in autopar staging environment.

**Key Findings:**
- staging.autopar.pitchai.net appears accessible
- autopar containers (redis, rabbitmq) running normally
- No critical error patterns detected

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Autopar System Status:**
✅ Website accessibility confirmed
✅ Container services operational  
✅ No critical autopar errors detected
✅ Staging environment stable

ℹ️ *Analysis performed using autopar pattern matching - Claude CLI not available*"""

    def parse_claude_response(self, response: str) -> tuple[str, str]:
        """Parse Claude's autopar analysis response."""
        print("🔍 Parsing Claude autopar analysis response...")

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
            print("  ⚠️  Unclear autopar response from Claude, defaulting to investigation")
            return "errors_investigate", f"STATUS: ERRORS_INVESTIGATE\nUnclear autopar response:\n{response}"

    async def send_autopar_notification(self, message_type: str, analysis: str):
        """Send autopar-specific Telegram notification."""
        try:
            from telegram_helper import send_telegram_message
            
            timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            
            if message_type == "all_good":
                emoji = "🟢"
                title = "AUTOPAR STAGING - ALL SYSTEMS HEALTHY"
                summary = """✅ **Website**: staging.autopar.pitchai.net accessible
✅ **Redis**: autopar-redis container healthy  
✅ **RabbitMQ**: autopar-rabbitmq container healthy
✅ **Logs**: No critical errors detected"""
                
            elif message_type == "suspicious_investigate":
                emoji = "⚠️"
                title = "AUTOPAR STAGING - SUSPICIOUS PATTERNS DETECTED"
                summary = "Some warning indicators found in autopar staging environment"
                
            else:  # errors_investigate
                emoji = "🚨"
                title = "AUTOPAR STAGING - CRITICAL ERRORS DETECTED"  
                summary = "Critical issues found in autopar staging environment"

            message = f"""{emoji} **AUTOPAR MONITORING - {title}**

📅 **Report Time**: {timestamp_str}
⏱️ **Period Analyzed**: {self.hours_back} hours
🎯 **Environment**: Autopar Staging
🤖 **Analysis**: Claude AI autopar monitoring

{summary}

🌐 **Website**: staging.autopar.pitchai.net
🐳 **Containers**: autopar-redis, autopar-rabbitmq

**📋 ANALYSIS DETAILS:**
{analysis[:1500]}{'...' if len(analysis) > 1500 else ''}

🔄 **Next Check**: {(self.timestamp + timedelta(hours=1)).strftime('%H:%M UTC')}

_Automated autopar monitoring by Claude Code Agent_"""

            if self.dry_run:
                print(f"  • DRY RUN: Would send autopar Telegram message:")
                print(f"    {message[:500]}...")
            else:
                success = await send_telegram_message(message)
                if success:
                    print(f"  • Autopar {message_type} notification sent via Telegram")
                else:
                    print(f"  • Failed to send autopar {message_type} notification")

        except Exception as e:
            print(f"❌ Error sending autopar notification: {e}")

    async def run_autopar_monitoring_workflow(self):
        """Execute the complete autopar monitoring workflow."""
        print("🚀 Starting Autopar Staging Monitoring Workflow")
        print(f"⏰ Analyzing last {self.hours_back} hours of autopar data")
        print(f"🔄 Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"🎯 Focus: staging.autopar.pitchai.net + autopar containers")
        print()

        try:
            # Step 1: Collect autopar-specific data
            autopar_data = self.collect_autopar_data()
            print(f"  ✅ Collected autopar monitoring data")

            # Step 2: Format for Claude analysis
            formatted_prompt = self.format_data_for_claude(autopar_data)
            print("  ✅ Formatted autopar prompt for Claude analysis")

            # Step 3: Execute Claude analysis  
            claude_response = self.execute_claude_analysis(formatted_prompt)
            print("  ✅ Received Claude autopar analysis response")

            # Step 4: Parse response and determine action
            action, analysis = self.parse_claude_response(claude_response)
            print(f"  ✅ Determined autopar action: {action.upper()}")

            # Step 5: Send appropriate autopar notification
            await self.send_autopar_notification(action, analysis)
            
            if action == "all_good":
                print("\n✅ AUTOPAR WORKFLOW COMPLETE: Staging environment healthy")
            elif action == "suspicious_investigate":
                print("\n⚠️  AUTOPAR WORKFLOW COMPLETE: Suspicious patterns investigated")
            elif action == "errors_investigate":
                print("\n🚨 AUTOPAR WORKFLOW COMPLETE: Critical errors investigated")

            return True

        except Exception as e:
            print(f"\n❌ AUTOPAR WORKFLOW FAILED: {e}")

            # Send error notification
            try:
                if not self.dry_run:
                    from telegram_helper import send_telegram_message
                    error_message = f"""⚠️ **AUTOPAR MONITORING SYSTEM ERROR**

Time: {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}
Environment: Autopar Staging  
Error: {str(e)}

The autopar monitoring agent encountered an error during execution.
Please check the autopar staging environment manually.

_Automated autopar error report_"""
                    await send_telegram_message(error_message)
            except:
                pass

            return False


async def main():
    """Main execution function for autopar monitoring."""
    parser = argparse.ArgumentParser(description="Autopar Staging Monitoring Agent")
    parser.add_argument("--hours", type=int, default=4,
                       help="Hours of logs to analyze (default: 4)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Run in dry-run mode (no actual notifications)")

    args = parser.parse_args()

    print("🚀 Autopar Staging Monitoring Agent")
    print("=" * 50)

    # Load environment
    if not load_environment():
        sys.exit(1)

    # Create and run autopar monitoring agent
    agent = AutoparMonitoringAgent(hours_back=args.hours, dry_run=args.dry_run)
    success = await agent.run_autopar_monitoring_workflow()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Autopar monitoring workflow completed successfully")
        print("Status Determined: Based on autopar staging environment analysis")
        sys.exit(0)
    else:
        print("💥 Autopar monitoring workflow failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())