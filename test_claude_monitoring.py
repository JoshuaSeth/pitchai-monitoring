#!/usr/bin/env python3
"""
Test Claude Monitoring with Simplified Data

This script tests the Claude monitoring workflow with a smaller dataset
to demonstrate the complete flow including Telegram notifications.
"""

import asyncio
import subprocess
import tempfile
from datetime import datetime

from telegram_helper import send_telegram_message


async def test_claude_monitoring():
    """Test the complete Claude monitoring workflow."""

    print("🎯 Testing Claude Monitoring Workflow")
    print("=" * 50)

    # Step 1: Create simplified monitoring data
    monitoring_data = """
================================================================================
UI TEST RESULTS
================================================================================
✅ ALL UI TESTS PASSED!
Test execution completed successfully.
Exit code: 0
Duration: 5.2 seconds

================================================================================
SYSTEM METRICS
================================================================================
DISK SPACE: 15% used (84GB available)
MEMORY USAGE: 45% used (8GB available)
CPU LOAD: 2.5 average
TOP PROCESSES: All normal

================================================================================
DOCKER STATUS
================================================================================
DOCKER VERSION: 27.5.1
RUNNING CONTAINERS: 5 containers healthy
All containers operating normally

================================================================================
ERROR ANALYSIS
================================================================================
No critical errors detected in the last hour.
Total error count: 0
System health: OPTIMAL
"""

    # Step 2: Create Claude prompt with proper instructions
    claude_prompt = f"""
<MONITORING_ANALYSIS_REQUEST>
<TIMESTAMP>{datetime.now().isoformat()}</TIMESTAMP>
<COLLECTION_PERIOD>1_hour</COLLECTION_PERIOD>

<INSTRUCTIONS>
You MUST respond with ONE of these three statuses:
1. STATUS: ALL_GOOD - No issues found
2. STATUS: SUSPICIOUS_INVESTIGATE - Concerning patterns need investigation
3. STATUS: ERRORS_INVESTIGATE - Clear errors found

Analyze the system data below.
</INSTRUCTIONS>

<SYSTEM_DATA>
{monitoring_data}
</SYSTEM_DATA>

<ANALYSIS_REQUEST>
Based on the data, what is your assessment? Start your response with the appropriate STATUS.
</ANALYSIS_REQUEST>
</MONITORING_ANALYSIS_REQUEST>"""

    # Step 3: Get Claude's analysis
    print("\n📋 Sending data to Claude for analysis...")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(claude_prompt)
        prompt_file = f.name

    try:
        result = subprocess.run(
            ['claude', '--dangerously-skip-permissions', '-p', prompt_file],
            capture_output=True,
            text=True,
            timeout=30
        )

        claude_response = result.stdout.strip()
        print(f"\n🤖 Claude's Response:\n{claude_response[:200]}...")

        # Step 4: Parse Claude's response
        if "STATUS: ALL_GOOD" in claude_response:
            status = "ALL_GOOD"
            emoji = "🟢"
            message_type = "All Systems Healthy"
        elif "STATUS: SUSPICIOUS_INVESTIGATE" in claude_response:
            status = "SUSPICIOUS_INVESTIGATE"
            emoji = "⚠️"
            message_type = "Suspicious Patterns Detected"
        elif "STATUS: ERRORS_INVESTIGATE" in claude_response:
            status = "ERRORS_INVESTIGATE"
            emoji = "🚨"
            message_type = "Critical Errors Detected"
        else:
            status = "UNKNOWN"
            emoji = "❓"
            message_type = "Unknown Status"

        print(f"\n✅ Status Determined: {status}")

        # Step 5: Send Telegram notification
        telegram_message = f"""{emoji} **CLAUDE MONITORING TEST**

📅 **Time**: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
🤖 **Claude Analysis**: {message_type}
🎯 **Status**: {status}

**System Summary:**
• UI Tests: ✅ All passing
• System Metrics: ✅ Normal
• Docker Status: ✅ Healthy
• Error Count: 0

**Claude's Assessment:**
{claude_response[:500]}...

_This is a test of the Claude monitoring system_"""

        print("\n📨 Sending Telegram notification...")
        success = await send_telegram_message(telegram_message)

        if success:
            print("✅ Telegram notification sent successfully!")
        else:
            print("❌ Failed to send Telegram notification")

    finally:
        import os
        os.unlink(prompt_file)

    print("\n" + "=" * 50)
    print("🎉 Test Complete!")
    print(f"• Claude Status: {status}")
    print(f"• Telegram Sent: {'✅ Yes' if success else '❌ No'}")

if __name__ == "__main__":
    asyncio.run(test_claude_monitoring())
