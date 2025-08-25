#!/usr/bin/env python3
"""
Final demonstration of Telegram integration with backlog processing
"""

from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"

def send_demo_messages():
    """Send a series of messages demonstrating the integration"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    messages = [
        {
            "text": "🚀 Starting AutoPAR Backlog Processing",
            "delay": 1
        },
        {
            "text": "📋 Task 1/3: Initialize System\n✅ Status: SUCCESS\n📝 Output: System initialized successfully",
            "delay": 2
        },
        {
            "text": "📋 Task 2/3: Process Data\n✅ Status: SUCCESS\n📝 Output: Data processed, 150 items completed",
            "delay": 2
        },
        {
            "text": "📋 Task 3/3: Generate Reports\n✅ Status: SUCCESS\n📝 Output: Reports generated and saved",
            "delay": 2
        },
        {
            "text": f"🎉 Backlog Processing Complete!\n\n📊 Summary:\n• Total Tasks: 3\n• Successful: 3\n• Failed: 0\n• Time: {datetime.now().strftime('%H:%M:%S')}\n\n✅ All tasks completed successfully!",
            "delay": 1
        }
    ]

    print("=" * 60)
    print("📱 TELEGRAM INTEGRATION DEMONSTRATION")
    print("=" * 60)
    print(f"Sending messages to chat ID: {CHAT_ID}")
    print()

    for i, msg in enumerate(messages, 1):
        data = {
            "chat_id": CHAT_ID,
            "text": msg["text"]
        }

        response = requests.post(url, json=data)
        result = response.json()

        if result.get("ok"):
            print(f"✅ Message {i}/5 sent (ID: {result['result']['message_id']})")
        else:
            print(f"❌ Failed to send message {i}: {result}")

        import time
        if i < len(messages):
            time.sleep(msg["delay"])

    print()
    print("=" * 60)
    print("✅ DEMONSTRATION COMPLETE!")
    print("=" * 60)
    print()
    print("You should now see 5 messages in your Telegram chat:")
    print("1. Processing start notification")
    print("2-4. Individual task completions")
    print("5. Final summary")
    print()
    print("This is exactly how run_backlog.py will send notifications")
    print("when processing real backlog items with --telegram flag!")

if __name__ == "__main__":
    send_demo_messages()
