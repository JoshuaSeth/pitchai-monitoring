#!/usr/bin/env python3
"""
Complete test to verify Telegram integration works end-to-end
"""

import time
from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"  # Seth van der Bijl's chat

def send_message(text):
    """Send a message via Telegram API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }

    response = requests.post(url, json=data)
    return response.json()

def test_backlog_notification():
    """Send a sample backlog completion notification"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    message = f"""🎯 *Task Completed (1/1)*
────────────────
📋 *Task:* Test Telegram Integration
✅ *Status:* SUCCESS
📝 *Output:* Telegram bot notifications are working correctly! Messages are being delivered successfully.
⏰ *Time:* {timestamp}

🚀 *AutoPAR Backlog Processing System*
All notifications are now active and will be sent when tasks complete."""

    print(f"📤 Sending test notification to chat {CHAT_ID}...")
    result = send_message(message)

    if result.get("ok"):
        print("✅ Message sent successfully!")
        print(f"   Message ID: {result['result']['message_id']}")
        print(f"   Date: {datetime.fromtimestamp(result['result']['date'])}")
        return True
    else:
        print(f"❌ Failed to send: {result}")
        return False

def test_simple_message():
    """Send a simple test message"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    message = f"🤖 Test message from AutoPAR at {timestamp}"

    print(f"📤 Sending simple test to chat {CHAT_ID}...")
    result = send_message(message)

    if result.get("ok"):
        print("✅ Simple message sent!")
        return True
    else:
        print(f"❌ Failed: {result}")
        return False

def main():
    print("=" * 50)
    print("🧪 TELEGRAM INTEGRATION VERIFICATION")
    print("=" * 50)
    print(f"Bot Token: {BOT_TOKEN[:20]}...")
    print(f"Chat ID: {CHAT_ID} (Seth van der Bijl)")
    print()

    # Test 1: Simple message
    print("Test 1: Simple Message")
    print("-" * 30)
    if test_simple_message():
        print("✅ Test 1 PASSED\n")
    else:
        print("❌ Test 1 FAILED\n")
        return

    time.sleep(1)

    # Test 2: Backlog notification
    print("Test 2: Backlog Notification")
    print("-" * 30)
    if test_backlog_notification():
        print("✅ Test 2 PASSED\n")
    else:
        print("❌ Test 2 FAILED\n")
        return

    print("=" * 50)
    print("🎉 ALL TESTS PASSED!")
    print("Telegram integration is working correctly.")
    print("\nYou should now see 2 messages in your Telegram chat:")
    print("1. A simple test message")
    print("2. A sample backlog completion notification")
    print("\nCheck your Telegram app to confirm!")

if __name__ == "__main__":
    main()
