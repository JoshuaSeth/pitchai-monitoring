#!/usr/bin/env python3
"""
Automatic Telegram chat ID finder and config updater
"""

import json
import urllib.parse
import urllib.request

BOT_TOKEN = "8401506310:AAG6--DeXCSxIbsmSbYaGLB3G5RTqhIewLM"

def get_bot_info():
    """Get bot information"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            if data['ok']:
                return data['result']
    except Exception as e:
        print(f"Error getting bot info: {e}")
    return None

def get_updates():
    """Get recent messages sent to the bot"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())
            if data['ok']:
                return data['result']
    except Exception as e:
        print(f"Error getting updates: {e}")
    return None

def send_test_message(chat_id):
    """Send a test message to verify the chat ID"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    message = "✅ Configuration updated! Your Telegram notifications are now active for PitchAI monitoring."

    params = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            return result['ok']
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def main():
    print("🤖 Telegram Chat ID Finder (Automatic)")
    print("=" * 50)
    print()

    # Get bot info
    bot_info = get_bot_info()
    if bot_info:
        bot_username = bot_info.get('username', 'unknown')
        print(f"✅ Connected to bot: @{bot_username}")
    else:
        print("⚠️ Could not connect to bot")
        bot_username = "pitchai_dev_bot"

    # Get updates without waiting for input
    print("\n🔍 Checking for recent messages to the bot...")
    updates = get_updates()

    if updates:
        # Extract unique chat IDs
        chat_ids = {}
        for update in updates:
            if 'message' in update:
                msg = update['message']
                chat = msg.get('chat', {})
                chat_id = chat.get('id')

                if chat_id and chat_id not in chat_ids:
                    from_user = msg.get('from', {})
                    chat_ids[chat_id] = {
                        'type': chat.get('type', 'private'),
                        'username': chat.get('username') or from_user.get('username'),
                        'first_name': chat.get('first_name') or from_user.get('first_name'),
                        'last_name': chat.get('last_name') or from_user.get('last_name'),
                        'last_message': msg.get('text', ''),
                        'date': msg.get('date')
                    }

        if chat_ids:
            print(f"\n✅ Found {len(chat_ids)} chat ID(s):")

            # Sort by most recent message
            sorted_chats = sorted(chat_ids.items(), key=lambda x: x[1].get('date', 0), reverse=True)

            for idx, (chat_id, info) in enumerate(sorted_chats, 1):
                print(f"\n  {idx}. Chat ID: {chat_id}")
                print(f"     Type: {info['type']}")
                if info['username']:
                    print(f"     Username: @{info['username']}")
                if info['first_name']:
                    name = info['first_name']
                    if info['last_name']:
                        name += f" {info['last_name']}"
                    print(f"     Name: {name}")
                if info['last_message']:
                    msg_preview = info['last_message'][:50]
                    if len(info['last_message']) > 50:
                        msg_preview += "..."
                    print(f"     Last message: {msg_preview}")

            # Use the most recent chat (first in sorted list)
            most_recent_chat_id = sorted_chats[0][0]
            most_recent_info = sorted_chats[0][1]

            print("\n" + "=" * 50)
            print(f"\n🎯 Using most recent chat ID: {most_recent_chat_id}")

            if most_recent_info['username']:
                print(f"   From user: @{most_recent_info['username']}")
            elif most_recent_info['first_name']:
                print(f"   From: {most_recent_info['first_name']}")

            # Update config file
            print("\n📝 Updating config file...")
            config_path = "config/telegram_config.json"
            try:
                config = {
                    "bot_token": BOT_TOKEN,
                    "chat_id": str(most_recent_chat_id),
                    "enabled": True,
                    "_note": "Auto-configured with correct chat ID"
                }

                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                print(f"✅ Config updated: {config_path}")
                print("   Chat ID changed from: 5246077032")
                print(f"   Chat ID updated to: {most_recent_chat_id}")

                # Send confirmation message
                print("\n🧪 Sending confirmation message...")
                if send_test_message(most_recent_chat_id):
                    print("✅ Confirmation message sent successfully!")
                    print("\n🎉 Telegram notifications are now configured correctly!")
                    print(f"   Bot: @{bot_username}")
                    print(f"   Chat ID: {most_recent_chat_id}")
                    print("   Status: Active")
                else:
                    print("⚠️ Could not send confirmation message")
                    print("   But config has been updated successfully")

            except Exception as e:
                print(f"❌ Error updating config: {e}")
                print(f"\nPlease manually update {config_path} with:")
                print(f'   "chat_id": "{most_recent_chat_id}"')
        else:
            print("\n❌ No messages found!")
            print("\nTo configure Telegram notifications:")
            print(f"1. Open Telegram and search for @{bot_username}")
            print("2. Start a chat with the bot")
            print("3. Send any message to the bot")
            print("4. Run this script again")

            # Show current config
            print("\n📋 Current configuration:")
            print(f"   Bot token: {BOT_TOKEN[:20]}...")
            print("   Chat ID: 5246077032 (needs update)")
    else:
        print("\n❌ Could not retrieve messages from Telegram")
        print("Please check your internet connection")

if __name__ == "__main__":
    main()
