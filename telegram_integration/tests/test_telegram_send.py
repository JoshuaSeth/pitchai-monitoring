#!/usr/bin/env python3
"""
Test script to send a message to Telegram bot and verify it works
"""

import json
from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"

def get_updates():
    """Get recent updates to find chat IDs"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    response = requests.get(url)
    return response.json()

def send_test_message(chat_id):
    """Send a test message to verify the bot works"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    message = f"""🚀 AutoPAR Telegram Integration Test

✅ Bot is working correctly!
📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔧 System: Backlog Processing Notifications
📊 Status: Ready to send task completion updates

This confirms the Telegram bot integration is functional and ready to send notifications when backlog tasks are completed."""

    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    response = requests.post(url, json=data)
    return response.json()

def main():
    print("🔍 Checking for available chats...")

    # Get updates to find chat IDs
    updates = get_updates()

    if updates.get("ok"):
        results = updates.get("result", [])

        if results:
            # Get unique chat IDs
            chat_ids = set()
            for update in results:
                if "message" in update:
                    chat_id = update["message"]["chat"]["id"]
                    chat_ids.add(chat_id)
                elif "channel_post" in update:
                    chat_id = update["channel_post"]["chat"]["id"]
                    chat_ids.add(chat_id)

            if chat_ids:
                print(f"✅ Found {len(chat_ids)} chat(s)")

                for chat_id in chat_ids:
                    print(f"\n📤 Sending test message to chat ID: {chat_id}")
                    result = send_test_message(chat_id)

                    if result.get("ok"):
                        print("✅ Message sent successfully!")
                        print(f"Message ID: {result['result']['message_id']}")
                        print(f"Chat ID: {result['result']['chat']['id']}")

                        # Save the working chat ID
                        config = {
                            "bot_token": BOT_TOKEN,
                            "chat_id": str(chat_id),
                            "enabled": True,
                            "_note": "Auto-configured after successful test"
                        }

                        with open("telegram_config.json", "w") as f:
                            json.dump(config, f, indent=2)

                        print("\n✅ Configuration saved to telegram_config.json")
                        print(f"Chat ID {chat_id} is now configured for notifications")
                    else:
                        print(f"❌ Failed to send message: {result}")
            else:
                print("❌ No chat IDs found. Please message the bot first at: https://t.me/pitchai_dev_bot")
        else:
            print("❌ No messages found. Please send a message to @pitchai_dev_bot first")
    else:
        print(f"❌ Failed to get updates: {updates}")

if __name__ == "__main__":
    main()
