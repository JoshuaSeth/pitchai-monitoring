#!/usr/bin/env python3
"""
Test Telegram Formatting with HTML Entities

This script tests the new markdown-to-HTML conversion functionality
for properly formatted Telegram messages.
"""

import asyncio
from telegram_helper import send_telegram_message, convert_markdown_to_html

async def test_telegram_formatting():
    """Test various formatting options with Telegram."""
    
    print("🧪 Testing Telegram HTML Formatting")
    print("=" * 50)
    
    # Test 1: Basic markdown conversion
    test_markdown = """**🤖 MONITORING TEST - HTML FORMATTING**

📅 **Alert Time**: 2025-08-25 16:30 UTC
⚠️ **Status**: Testing HTML entities

**🔍 ANALYSIS:**
• *System metrics*: All normal
• `Memory usage`: 45% (within limits)
• **Docker containers**: 5 running
• ~~Old issue~~: Resolved

**📋 CODE EXAMPLE:**
```python
def test_function():
    return "success"
```

**⚡ CONCLUSION:**
HTML formatting test with *italics*, **bold**, `code`, and ~~strikethrough~~.

_Automated test message_"""

    print("Original markdown:")
    print(test_markdown)
    print("\n" + "=" * 30)
    
    # Test conversion
    converted_html = convert_markdown_to_html(test_markdown)
    print("Converted to HTML entities:")
    print(converted_html)
    print("\n" + "=" * 30)
    
    # Test 2: Send formatted message
    print("Sending formatted message to Telegram...")
    success = await send_telegram_message(test_markdown)
    
    if success:
        print("✅ HTML formatted message sent successfully!")
    else:
        print("❌ Failed to send formatted message")
    
    # Test 3: Send without auto-conversion (raw HTML)
    print("\nSending raw HTML message...")
    raw_html_message = """<b>🔧 RAW HTML TEST</b>

<i>This message uses raw HTML entities</i>:
• <code>system.status</code>: OK
• <b>Memory</b>: 2.1GB available  
• <s>Previous error</s>: Resolved

<pre>
docker ps -a
CONTAINER ID   STATUS
abc123def      Up 2 hours
</pre>

<b>Status</b>: <i>Raw HTML formatting test</i>"""

    success2 = await send_telegram_message(raw_html_message, auto_convert=False, parse_mode='HTML')
    
    if success2:
        print("✅ Raw HTML message sent successfully!")
    else:
        print("❌ Failed to send raw HTML message")
    
    # Test 4: Complex monitoring alert format
    print("\nSending complex monitoring alert...")
    complex_alert = """🚨 **MONITORING ALERT - SUSPICIOUS INVESTIGATE**

📅 **Alert Time**: 2025-08-25 16:35 UTC
⏱️ **Period Analyzed**: 2 hours
🤖 **Detected By**: Claude AI monitoring agent
🎯 **Severity**: SUSPICIOUS

**🔍 CLAUDE ANALYSIS:**
Claude detected the following concerning patterns:
• *High memory usage*: 85% (warning threshold)
• **Container restarts**: `afasa-backend` restarted 3 times
• API response time: `avg 2.3s` (normally `0.5s`)

**📋 INVESTIGATION RESULTS:**
```
Investigation Status: COMPLETED
Areas Checked:
- Container logs: No critical errors
- System resources: Memory pressure detected  
- Network connectivity: All endpoints responding
- Database connections: Pool utilization at 90%
```

**⚡ INVESTIGATION RECOMMENDED:**
Monitor situation and investigate when convenient.

**📊 DETAILED REPORTS:**
Check the monitoring reports directory for complete details.

**🛡️ INFRA-AGENT:**
Suspicious pattern analysis completed.

_Automated monitoring by Claude Code Agent_"""

    success3 = await send_telegram_message(complex_alert)
    
    if success3:
        print("✅ Complex monitoring alert sent successfully!")
    else:
        print("❌ Failed to send complex monitoring alert")
    
    print("\n" + "=" * 50)
    print("🎉 Formatting Test Complete!")
    print(f"• Basic markdown conversion: {'✅ Pass' if success else '❌ Fail'}")
    print(f"• Raw HTML entities: {'✅ Pass' if success2 else '❌ Fail'}")  
    print(f"• Complex monitoring alert: {'✅ Pass' if success3 else '❌ Fail'}")

if __name__ == "__main__":
    asyncio.run(test_telegram_formatting())