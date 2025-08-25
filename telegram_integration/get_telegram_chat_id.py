#!/usr/bin/env python3
"""
Helper script to get your Telegram chat ID for configuring the bot
"""

import json

from telegram_notifier import TelegramNotifier


def main():
    # Load config to get bot token
    try:
        with open("telegram_config.json") as f:
            config = json.load(f)
        bot_token = config.get("bot_token")
    except:
        bot_token = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"

    print("🤖 Telegram Chat ID Finder")
    print("=" * 50)
    print()

    # Initialize bot
    notifier = TelegramNotifier(bot_token)

    # Get bot info
    bot_info = notifier.get_bot_info()
    if bot_info:
        print(f"✅ Connected to bot: @{bot_info.get('username', 'unknown')}")
        print()

    print("📋 Instructions:")
    print("1. Open Telegram on your phone or computer")
    print(f"2. Search for @{bot_info.get('username', 'pitchai_dev_bot')}")
    print("3. Start a chat and send any message (e.g., 'Hello')")
    print("4. Press Enter here to check for your chat ID...")
    input()

    # Get updates
    print("\n🔍 Checking for messages...")
    updates = notifier.get_updates()

    if updates:
        chat_ids = notifier.get_chat_ids_from_updates(updates)

        if chat_ids:
            print("\n✅ Found chat IDs:")
            for chat_id, info in chat_ids.items():
                print(f"\n  Chat ID: {chat_id}")
                print(f"  Type: {info['type']}")
                if info['username']:
                    print(f"  Username: @{info['username']}")
                if info['first_name']:
                    print(f"  Name: {info['first_name']} {info.get('last_name', '')}")
                print(f"  Last message: {info['last_message'][:50]}...")

            print("\n📝 To use this chat ID:")
            print("1. Copy the Chat ID number above")
            print("2. Open telegram_config.json")
            print("3. Replace YOUR_CHAT_ID_HERE with the number")
            print("4. Set 'enabled' to true")

            # Offer to test
            if len(chat_ids) == 1:
                chat_id = list(chat_ids.keys())[0]
                print(f"\n🧪 Would you like to send a test message to chat {chat_id}?")
                response = input("Type 'yes' to send test message: ")
                if response.lower() == 'yes':
                    success = notifier.send_message(
                        chat_id,
                        "✅ Test successful! Your Telegram notifications are configured correctly."
                    )
                    if success:
                        print("✅ Test message sent successfully!")
                    else:
                        print("❌ Failed to send test message")
        else:
            print("\n❌ No messages found!")
            print("Make sure you've sent a message to the bot and try again.")
    else:
        print("\n❌ Could not retrieve updates from Telegram")
        print("Please check your internet connection and try again")

if __name__ == "__main__":
    main()
