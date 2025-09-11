#!/usr/bin/env python3
"""
Quickchat Monitoring Agent

This script monitors the chat.pitchai.net website and its associated
Docker containers with the same comprehensive approach as the main production 
monitoring system.

Runs on the same schedule as the main monitoring agent and provides:
1. Website health monitoring for chat.pitchai.net  
2. Quickchat UI test execution and validation
3. Container-specific log analysis for quickchat containers
4. Claude AI-powered analysis and alerts
5. Telegram notifications for quickchat-specific issues

Usage:
    python quickchat_monitoring_agent.py [--hours 4] [--dry-run]
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


class QuickchatMonitoringAgent:
    """Specialized monitoring agent for Quickchat environment."""

    def __init__(self, hours_back: int = 4, dry_run: bool = False):
        self.hours_back = hours_back
        self.dry_run = dry_run
        self.timestamp = datetime.utcnow()
        self.quickchat_containers = ['chat-app', 'chat-redis', 'chat-postgres', 'chat-nginx']  # Likely containers
        self.chat_url = 'https://chat.pitchai.net'
        self.test_url = 'https://chat.pitchai.net/chat/ortho_ridderkerk/test'

    def collect_quickchat_data(self) -> str:
        """Collect comprehensive quickchat-specific monitoring data."""
        print("🔄 Collecting Quickchat monitoring data...")

        data_sections = []

        # Website health check
        website_status = self.check_website_health()
        data_sections.append(f"QUICKCHAT WEBSITE HEALTH:\n{website_status}")

        # UI test execution
        ui_test_results = self.run_quickchat_ui_tests()
        data_sections.append(f"QUICKCHAT UI TEST RESULTS:\n{ui_test_results}")

        # Container status and logs
        container_status = self.collect_container_status()
        data_sections.append(f"QUICKCHAT CONTAINER STATUS:\n{container_status}")

        # Detailed container logs
        container_logs = self.collect_container_logs()
        data_sections.append(f"QUICKCHAT CONTAINER LOGS:\n{container_logs}")

        # System metrics for quickchat containers
        container_metrics = self.collect_container_metrics()
        data_sections.append(f"QUICKCHAT CONTAINER METRICS:\n{container_metrics}")

        # Error analysis
        error_analysis = self.analyze_quickchat_errors()
        data_sections.append(f"QUICKCHAT ERROR ANALYSIS:\n{error_analysis}")

        full_report = "\n" + "="*80 + "\n".join(data_sections)
        print(f"  ✅ Collected {len(full_report):,} characters of quickchat monitoring data")
        
        return full_report

    def check_website_health(self) -> str:
        """Check chat.pitchai.net website health."""
        print("  • Checking chat.pitchai.net health...")
        
        health_info = []
        
        try:
            # Basic connectivity check for main chat domain
            result = subprocess.run([
                'curl', '-I', '-s', '--max-time', '10', self.chat_url
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                health_info.append(f"✅ Main chat website accessible: {self.chat_url}")
                health_info.append(f"HTTP Response Headers:\n{result.stdout}")
            else:
                health_info.append(f"❌ Main chat website inaccessible: {self.chat_url}")
                health_info.append(f"Error: {result.stderr}")

            # Test the specific chat endpoint
            test_result = subprocess.run([
                'curl', '-I', '-s', '--max-time', '10', self.test_url
            ], capture_output=True, text=True, timeout=15)
            
            if test_result.returncode == 0:
                health_info.append(f"✅ Chat test endpoint accessible: {self.test_url}")
                health_info.append(f"Response headers: {test_result.stdout[:200]}...")
            else:
                health_info.append(f"❌ Chat test endpoint inaccessible: {self.test_url}")
                health_info.append(f"Error: {test_result.stderr}")

            # Try to get content from main page
            content_result = subprocess.run([
                'curl', '-s', '--max-time', '10', self.chat_url
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
                endpoint_url = f"{self.chat_url}{endpoint}"
                endpoint_result = subprocess.run([
                    'curl', '-s', '--max-time', '5', endpoint_url
                ], capture_output=True, text=True, timeout=10)
                
                if endpoint_result.returncode == 0 and endpoint_result.stdout:
                    health_info.append(f"✅ Endpoint {endpoint}: {endpoint_result.stdout[:100]}")

        except Exception as e:
            health_info.append(f"❌ Error checking website health: {str(e)}")

        return '\n'.join(health_info)

    def run_quickchat_ui_tests(self) -> str:
        """Run the quickchat UI test and collect results."""
        print("  • Running quickchat UI tests...")
        
        test_results = []
        
        try:
            # Run the specific quickchat UI test
            result = subprocess.run([
                'npx', 'playwright', 'test', 'tests/chat_interaction_test.spec.js', '--reporter=json'
            ], capture_output=True, text=True, timeout=300, cwd=".")
            
            if result.returncode == 0:
                test_results.append("🎭 ✅ QUICKCHAT UI TESTS PASSED!")
                test_results.append("Chat interaction test completed successfully.")
                test_results.append(f"Exit code: {result.returncode}")
                
                # Extract useful info from output
                if result.stdout:
                    output_lines = result.stdout.split('\n')
                    for line in output_lines[-10:]:
                        if any(word in line.lower() for word in ['passed', 'test', 'duration', 'chat']):
                            test_results.append(f"  {line.strip()}")
                            
            else:
                # UI TESTS FAILED - Critical for quickchat
                test_results.append("🎭 🚨 QUICKCHAT UI TESTS FAILED - CRITICAL!")
                test_results.append(f"Exit code: {result.returncode}")
                test_results.append("")
                
                # Include detailed failure information
                if result.stdout:
                    test_results.append("STDOUT OUTPUT:")
                    stdout_lines = result.stdout.split('\n')
                    # Look for failures, errors, and summary
                    relevant_lines = []
                    for line in stdout_lines:
                        line_lower = line.lower()
                        if any(keyword in line_lower for keyword in ['fail', 'error', 'timeout', 'expect', 'chat']):
                            relevant_lines.append(f"  {line.strip()}")
                    
                    if relevant_lines:
                        test_results.extend(relevant_lines)
                    else:
                        test_results.extend([f"  {line.strip()}" for line in stdout_lines[-15:] if line.strip()])

                if result.stderr:
                    test_results.append("")
                    test_results.append("STDERR OUTPUT:")
                    stderr_lines = result.stderr.split('\n')
                    test_results.extend([f"  {line.strip()}" for line in stderr_lines if line.strip()])

        except subprocess.TimeoutExpired:
            test_results.append("🎭 🚨 QUICKCHAT UI TESTS TIMED OUT - CRITICAL ISSUE!")
            test_results.append("Tests exceeded 5 minute timeout limit.")
        except Exception as e:
            test_results.append(f"🎭 🚨 ERROR RUNNING QUICKCHAT UI TESTS - CRITICAL ISSUE!")
            test_results.append(f"Error: {str(e)}")

        return '\n'.join(test_results)

    def collect_container_status(self) -> str:
        """Collect status of quickchat containers."""
        print("  • Collecting quickchat container status...")
        
        status_info = []
        
        try:
            # Check if quickchat containers are running
            for container in self.quickchat_containers:
                result = subprocess.run([
                    'docker', 'ps', '--filter', f'name={container}', 
                    '--format', 'table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}'
                ], capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    if container in result.stdout:
                        status_info.append(f"✅ {container} container status:")
                        status_info.append(f"   {result.stdout}")
                    else:
                        status_info.append(f"⚠️  {container} container not found (may use different name)")
                else:
                    status_info.append(f"❌ Error checking {container}: {result.stderr}")

            # Try to find any chat-related containers
            all_containers_result = subprocess.run([
                'docker', 'ps', '--format', 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
            ], capture_output=True, text=True, timeout=10)
            
            if all_containers_result.returncode == 0:
                chat_containers = []
                for line in all_containers_result.stdout.split('\n'):
                    if any(keyword in line.lower() for keyword in ['chat', 'quickchat']):
                        chat_containers.append(line)
                
                if chat_containers:
                    status_info.append("\n🔍 Found chat-related containers:")
                    for container in chat_containers:
                        status_info.append(f"   {container}")

            # Get container resource usage for any found containers
            for container in self.quickchat_containers:
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
        """Collect detailed logs from quickchat containers."""
        print("  • Collecting quickchat container logs...")
        
        logs_info = []
        since_time = datetime.utcnow() - timedelta(hours=self.hours_back)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
        
        for container in self.quickchat_containers:
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
                    logs_info.append(f"⚠️  Container {container} not found - may not exist or use different name")

            except Exception as e:
                logs_info.append(f"❌ Exception getting logs for {container}: {str(e)}")

        return '\n'.join(logs_info)

    def collect_container_metrics(self) -> str:
        """Collect detailed metrics for quickchat containers."""
        print("  • Collecting quickchat container metrics...")
        
        metrics_info = []
        
        try:
            # Docker system df for quickchat containers
            result = subprocess.run([
                'docker', 'system', 'df'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                metrics_info.append("DOCKER SYSTEM USAGE:")
                metrics_info.append(result.stdout)

            # Inspect each container for detailed info
            for container in self.quickchat_containers:
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

    def analyze_quickchat_errors(self) -> str:
        """Analyze errors specific to quickchat containers and website."""
        print("  • Analyzing quickchat-specific errors...")
        
        error_analysis = []
        error_count = 0
        warning_count = 0
        
        # Error patterns specific to quickchat/chat systems
        quickchat_error_patterns = [
            'error', 'exception', 'failed', 'timeout', 'connection refused',
            'websocket error', 'chat error', 'message failed', 'authentication failed',
            'permission denied', 'broken pipe', 'database connection failed',
            'redis error', 'postgres error', 'nginx error', '502 bad gateway'
        ]
        
        warning_patterns = [
            'warning', 'retry', 'reconnect', 'degraded', 'slow response',
            'rate limit', 'queue full', 'memory high', 'cpu high'
        ]
        
        # Analyze logs from each container
        since_time = datetime.utcnow() - timedelta(hours=self.hours_back)
        since_str = since_time.strftime('%Y-%m-%dT%H:%M:%S')
        
        for container in self.quickchat_containers:
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
                        for pattern in quickchat_error_patterns:
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
                error_analysis.append(f"⚠️  Could not analyze {container}: {str(e)}")

        # Summary
        error_analysis.insert(0, f"QUICKCHAT ERROR SUMMARY (last {self.hours_back} hours):")
        error_analysis.insert(1, f"Total Errors: {error_count}")
        error_analysis.insert(2, f"Total Warnings: {warning_count}")
        error_analysis.insert(3, f"Containers Analyzed: {len(self.quickchat_containers)}")

        if error_count == 0 and warning_count == 0:
            error_analysis.append("\n✅ NO ERRORS OR WARNINGS DETECTED in Quickchat system!")

        return '\n'.join(error_analysis)

    def format_data_for_claude(self, quickchat_data: str) -> str:
        """Format quickchat monitoring data for Claude analysis."""
        print("📋 Formatting quickchat data for Claude analysis...")

        formatted_prompt = f"""
<QUICKCHAT_MONITORING_ANALYSIS_REQUEST>
<TIMESTAMP>{self.timestamp.isoformat()}</TIMESTAMP>
<COLLECTION_PERIOD>{self.hours_back}_hours</COLLECTION_PERIOD>
<FOCUS>QUICKCHAT_SYSTEM_ENVIRONMENT</FOCUS>

<INSTRUCTIONS>
You are an expert system monitoring agent analyzing the QUICKCHAT system environment.

FOCUS AREAS:
- chat.pitchai.net website health and accessibility
- Quickchat UI test results (chat interaction functionality)
- Chat-related container health (chat-app, chat-redis, chat-postgres, chat-nginx)
- Chat-specific error patterns and performance issues
- User experience and chat functionality

CRITICAL RESPONSE FORMATS - You MUST respond with ONE of these three statuses:

1. **STATUS: ALL_GOOD**
   - Use when chat website is accessible and UI tests pass
   - No errors, crashes, or suspicious patterns in chat services
   - Chat functionality working correctly

2. **STATUS: SUSPICIOUS_INVESTIGATE**
   - Use when you find concerning patterns in quickchat services
   - Examples: slow chat responses, minor connection issues, performance warnings
   - These require investigation to prevent chat service degradation

3. **STATUS: ERRORS_INVESTIGATE**
   - Use when you find clear quickchat service failures or critical issues
   - Examples: website down, UI tests failing, container crashes, chat not working
   - These require immediate investigation and resolution

QUICKCHAT-SPECIFIC ANALYSIS:
- Website Response: Check HTTP status, response times, content errors for chat.pitchai.net
- UI Test Results: Monitor chat interaction test success/failure - CRITICAL INDICATOR
- Container Health: Monitor chat containers, restarts, resource usage, error patterns
- Chat Functionality: Analyze websocket connections, message delivery, user experience
- Service Dependencies: Analyze inter-service communication issues

INVESTIGATION REQUIREMENTS:
When you determine investigation is needed (SUSPICIOUS_INVESTIGATE or ERRORS_INVESTIGATE):
- You MUST ACTUALLY USE the monitoring-infra-engineer agent for investigation
- Focus specifically on quickchat system issues
- The monitoring-infra-engineer MUST operate in READ-ONLY mode - NO changes
- Tell the monitoring-infra-engineer: "READ-ONLY investigation of QUICKCHAT SYSTEM only"
- Collect investigation results and include them in your response

DECISION LOGIC FOR QUICKCHAT:
- Website down, UI tests failed, or containers crashed → STATUS: ERRORS_INVESTIGATE
- Performance warnings, slow responses, minor errors → STATUS: SUSPICIOUS_INVESTIGATE  
- All services healthy and chat tests passing → STATUS: ALL_GOOD
</INSTRUCTIONS>

<QUICKCHAT_SYSTEM_DATA>
{quickchat_data}
</QUICKCHAT_SYSTEM_DATA>

<ANALYSIS_REQUEST>
Analyze the above QUICKCHAT SYSTEM data thoroughly and provide your assessment.

Your response MUST start with exactly one of:
- "STATUS: ALL_GOOD"
- "STATUS: SUSPICIOUS_INVESTIGATE" 
- "STATUS: ERRORS_INVESTIGATE"

YOUR RESPONSE MUST INCLUDE:
1. The status line for quickchat system environment
2. Your analysis of quickchat website and UI test results
3. IF INVESTIGATING: Complete investigation report from the infra-agent
4. Quickchat-specific recommendations and findings
5. Summary focused on chat functionality and user experience

CRITICAL: Focus on QUICKCHAT SYSTEM only - investigate chat-specific issues!
</ANALYSIS_REQUEST>
</QUICKCHAT_MONITORING_ANALYSIS_REQUEST>"""

        return formatted_prompt

    def execute_claude_analysis(self, formatted_prompt: str) -> str:
        """Execute Claude command with quickchat monitoring data."""
        print("🤖 Executing Claude analysis for Quickchat system...")

        try:
            # Create temporary file for the prompt
            import uuid
            temp_file_path = f"quickchat_claude_prompt_{uuid.uuid4().hex[:8]}.txt"
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
                    return self._quickchat_pattern_analysis(formatted_prompt)
                
                # Execute Claude command
                cmd = [claude_cmd, '-p', temp_file_path]
                print(f"  • Running: {cmd[0]} -p <quickchat_prompt_file>")

                if self.dry_run:
                    print("  • DRY RUN: Would execute Claude command for quickchat analysis")
                    return "STATUS: ALL_GOOD\nDry run mode - no actual quickchat analysis performed."

                print("  • ⏳ Claude is analyzing quickchat system...")
                print("  • This may take time for comprehensive quickchat analysis")

                # Claude analysis with timeout
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

                if result.returncode != 0:
                    raise Exception(f"Claude command failed: {result.stderr}")

                return result.stdout.strip()

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception as e:
            print(f"❌ Error executing Claude analysis for quickchat: {e}")
            raise

    def _quickchat_pattern_analysis(self, prompt: str) -> str:
        """Fallback pattern analysis for quickchat when Claude CLI unavailable."""
        print("  • Performing quickchat pattern analysis...")
        
        # Extract monitoring data
        if "<QUICKCHAT_SYSTEM_DATA>" in prompt:
            start = prompt.find("<QUICKCHAT_SYSTEM_DATA>") + len("<QUICKCHAT_SYSTEM_DATA>")
            end = prompt.find("</QUICKCHAT_SYSTEM_DATA>")
            monitoring_data = prompt[start:end].strip().lower()
        else:
            monitoring_data = prompt.lower()

        # Quickchat-specific error patterns
        critical_patterns = [
            'website inaccessible', 'ui tests failed', 'container not running', 
            'connection refused', 'chat error', 'websocket error', 'crashed',
            'exited', 'unhealthy', 'failed', 'exception', 'timeout'
        ]
        
        warning_patterns = [
            'warning', 'retry', 'slow', 'timeout', 'degraded', 'high cpu', 
            'high memory', 'rate limit', 'reconnect', 'queue full'
        ]
        
        healthy_patterns = [
            'website accessible', 'ui tests passed', 'container status', 'healthy', 
            'running', 'chat interaction test completed successfully'
        ]

        critical_count = sum(1 for pattern in critical_patterns if pattern in monitoring_data)
        warning_count = sum(1 for pattern in warning_patterns if pattern in monitoring_data)
        healthy_count = sum(1 for pattern in healthy_patterns if pattern in monitoring_data)

        print(f"  • Quickchat pattern analysis: {critical_count} critical, {warning_count} warnings, {healthy_count} healthy")

        if critical_count >= 2:
            return f"""STATUS: ERRORS_INVESTIGATE

**CRITICAL QUICKCHAT SYSTEM ISSUES DETECTED**

Found {critical_count} critical patterns in quickchat system monitoring data.

**Key Findings:**
- Quickchat system has critical issues
- Multiple error patterns detected in chat services or UI tests
- Immediate investigation required for chat.pitchai.net

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}  
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Check chat.pitchai.net accessibility immediately
2. Verify quickchat UI test results and functionality
3. Review chat container logs for critical errors
4. Monitor chat service dependencies and websockets

⚠️ *Analysis performed using quickchat pattern matching - Claude CLI not available*"""
            
        elif critical_count >= 1 or warning_count >= 3:
            return f"""STATUS: SUSPICIOUS_INVESTIGATE

**SUSPICIOUS QUICKCHAT SYSTEM PATTERNS DETECTED**

Found {critical_count} errors and {warning_count} warnings in quickchat system.

**Key Findings:**
- Some quickchat-specific warning patterns detected
- Chat system may have performance issues
- Monitoring recommended for chat services

**Pattern Analysis Summary:**  
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Recommended Actions:**
1. Monitor chat.pitchai.net response times
2. Check chat container resource usage
3. Review chat UI test performance
4. Verify websocket connections and message delivery

ℹ️ *Analysis performed using quickchat pattern matching - Claude CLI not available*"""
            
        else:
            return f"""STATUS: ALL_GOOD

**QUICKCHAT SYSTEM OPERATING NORMALLY**

No significant issues detected in quickchat system.

**Key Findings:**
- chat.pitchai.net appears accessible
- Chat UI tests likely passing
- Chat containers running normally

**Pattern Analysis Summary:**
- Critical Issues: {critical_count}
- Warning Indicators: {warning_count}
- Healthy Services: {healthy_count}

**Quickchat System Status:**
✅ Website accessibility confirmed
✅ Chat functionality operational  
✅ No critical chat errors detected
✅ UI tests stable

ℹ️ *Analysis performed using quickchat pattern matching - Claude CLI not available*"""

    def parse_claude_response(self, response: str) -> tuple[str, str]:
        """Parse Claude's quickchat analysis response."""
        print("🔍 Parsing Claude quickchat analysis response...")

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
            print("  ⚠️  Unclear quickchat response from Claude, defaulting to investigation")
            return "errors_investigate", f"STATUS: ERRORS_INVESTIGATE\nUnclear quickchat response:\n{response}"

    async def send_quickchat_notification(self, message_type: str, analysis: str):
        """Send quickchat-specific Telegram notification."""
        try:
            from telegram_helper import send_telegram_message
            
            timestamp_str = self.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            
            if message_type == "all_good":
                emoji = "💬"
                title = "QUICKCHAT SYSTEM - ALL SYSTEMS HEALTHY"
                summary = """✅ **Website**: chat.pitchai.net accessible
✅ **UI Tests**: Chat interaction tests passing  
✅ **Containers**: Chat services healthy
✅ **Functionality**: No critical errors detected"""
                
            elif message_type == "suspicious_investigate":
                emoji = "⚠️"
                title = "QUICKCHAT SYSTEM - SUSPICIOUS PATTERNS DETECTED"
                summary = "Some warning indicators found in quickchat system"
                
            else:  # errors_investigate
                emoji = "🚨"
                title = "QUICKCHAT SYSTEM - CRITICAL ERRORS DETECTED"  
                summary = "Critical issues found in quickchat system"

            message = f"""{emoji} **QUICKCHAT MONITORING - {title}**

📅 **Report Time**: {timestamp_str}
⏱️ **Period Analyzed**: {self.hours_back} hours
🎯 **Environment**: Quickchat System
🤖 **Analysis**: Claude AI quickchat monitoring

{summary}

🌐 **Website**: chat.pitchai.net
🎭 **UI Tests**: Chat interaction functionality
🐳 **Containers**: Chat services and dependencies

**📋 ANALYSIS DETAILS:**
{analysis[:1500]}{'...' if len(analysis) > 1500 else ''}

🔄 **Next Check**: {(self.timestamp + timedelta(hours=1)).strftime('%H:%M UTC')}

_Automated quickchat monitoring by Claude Code Agent_"""

            if self.dry_run:
                print(f"  • DRY RUN: Would send quickchat Telegram message:")
                print(f"    {message[:500]}...")
            else:
                success = await send_telegram_message(message)
                if success:
                    print(f"  • Quickchat {message_type} notification sent via Telegram")
                else:
                    print(f"  • Failed to send quickchat {message_type} notification")

        except Exception as e:
            print(f"❌ Error sending quickchat notification: {e}")

    async def run_quickchat_monitoring_workflow(self):
        """Execute the complete quickchat monitoring workflow."""
        print("🚀 Starting Quickchat System Monitoring Workflow")
        print(f"⏰ Analyzing last {self.hours_back} hours of quickchat data")
        print(f"🔄 Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"🎯 Focus: chat.pitchai.net + chat UI tests + chat containers")
        print()

        try:
            # Step 1: Collect quickchat-specific data
            quickchat_data = self.collect_quickchat_data()
            print(f"  ✅ Collected quickchat monitoring data")

            # Step 2: Format for Claude analysis
            formatted_prompt = self.format_data_for_claude(quickchat_data)
            print("  ✅ Formatted quickchat prompt for Claude analysis")

            # Step 3: Execute Claude analysis  
            claude_response = self.execute_claude_analysis(formatted_prompt)
            print("  ✅ Received Claude quickchat analysis response")

            # Step 4: Parse response and determine action
            action, analysis = self.parse_claude_response(claude_response)
            print(f"  ✅ Determined quickchat action: {action.upper()}")

            # Step 5: Send appropriate quickchat notification
            await self.send_quickchat_notification(action, analysis)
            
            if action == "all_good":
                print("\n✅ QUICKCHAT WORKFLOW COMPLETE: Chat system healthy")
            elif action == "suspicious_investigate":
                print("\n⚠️  QUICKCHAT WORKFLOW COMPLETE: Suspicious patterns investigated")
            elif action == "errors_investigate":
                print("\n🚨 QUICKCHAT WORKFLOW COMPLETE: Critical errors investigated")

            return True

        except Exception as e:
            print(f"\n❌ QUICKCHAT WORKFLOW FAILED: {e}")

            # Send error notification
            try:
                if not self.dry_run:
                    from telegram_helper import send_telegram_message
                    error_message = f"""⚠️ **QUICKCHAT MONITORING SYSTEM ERROR**

Time: {self.timestamp.strftime('%Y-%m-%d %H:%M UTC')}
Environment: Quickchat System  
Error: {str(e)}

The quickchat monitoring agent encountered an error during execution.
Please check the quickchat system manually.

_Automated quickchat error report_"""
                    await send_telegram_message(error_message)
            except:
                pass

            return False


async def main():
    """Main execution function for quickchat monitoring."""
    parser = argparse.ArgumentParser(description="Quickchat System Monitoring Agent")
    parser.add_argument("--hours", type=int, default=4,
                       help="Hours of logs to analyze (default: 4)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Run in dry-run mode (no actual notifications)")

    args = parser.parse_args()

    print("🚀 Quickchat System Monitoring Agent")
    print("=" * 50)

    # Load environment
    if not load_environment():
        sys.exit(1)

    # Create and run quickchat monitoring agent
    agent = QuickchatMonitoringAgent(hours_back=args.hours, dry_run=args.dry_run)
    success = await agent.run_quickchat_monitoring_workflow()

    print("\n" + "=" * 50)
    if success:
        print("🎉 Quickchat monitoring workflow completed successfully")
        print("Status Determined: Based on quickchat system analysis")
        sys.exit(0)
    else:
        print("💥 Quickchat monitoring workflow failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())