#!/usr/bin/env python3
"""
Simple script to get Telegram chat ID without external dependencies
"""

import json
import urllib.request
import urllib.parse

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"

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
    message = "✅ Test successful! Your chat ID is configured correctly."
    
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
    print("🤖 Telegram Chat ID Finder")
    print("=" * 50)
    print()
    
    # Get bot info
    bot_info = get_bot_info()
    if bot_info:
        bot_username = bot_info.get('username', 'unknown')
        print(f"✅ Connected to bot: @{bot_username}")
        print()
    else:
        print("⚠️ Could not connect to bot")
        bot_username = "pitchai_dev_bot"
    
    print("📋 Instructions:")
    print(f"1. Open Telegram and search for @{bot_username}")
    print("2. Start a chat with the bot")
    print("3. Send any message to the bot (e.g., 'Hello')")
    print("4. Press Enter here after sending the message...")
    input()
    
    # Get updates
    print("\n🔍 Checking for messages...")
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
                    chat_ids[chat_id] = {
                        'type': chat.get('type', 'private'),
                        'username': chat.get('username'),
                        'first_name': chat.get('first_name'),
                        'last_name': chat.get('last_name'),
                        'last_message': msg.get('text', ''),
                        'from_user': msg.get('from', {}).get('username')
                    }
        
        if chat_ids:
            print("\n✅ Found chat IDs:")
            for chat_id, info in chat_ids.items():
                print(f"\n  📍 Chat ID: {chat_id}")
                print(f"     Type: {info['type']}")
                if info['username']:
                    print(f"     Username: @{info['username']}")
                elif info['from_user']:
                    print(f"     From: @{info['from_user']}")
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
            
            print("\n" + "=" * 50)
            
            # If only one chat ID found, offer to test and update config
            if len(chat_ids) == 1:
                chat_id = list(chat_ids.keys())[0]
                print(f"\n🎯 Your chat ID is: {chat_id}")
                
                # Test message
                print(f"\n🧪 Sending test message to verify...")
                if send_test_message(chat_id):
                    print("✅ Test message sent successfully!")
                    
                    # Update config file
                    print("\n📝 Updating config file...")
                    config_path = "config/telegram_config.json"
                    try:
                        config = {
                            "bot_token": BOT_TOKEN,
                            "chat_id": str(chat_id),
                            "enabled": True,
                            "_note": "Auto-configured with correct chat ID"
                        }
                        
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=2)
                        
                        print(f"✅ Config updated: {config_path}")
                        print(f"   Chat ID set to: {chat_id}")
                        print("\n🎉 Telegram notifications are now configured!")
                    except Exception as e:
                        print(f"⚠️ Could not update config automatically: {e}")
                        print(f"\nPlease manually update {config_path} with:")
                        print(f'   "chat_id": "{chat_id}"')
                else:
                    print("⚠️ Could not send test message")
                    print(f"\nYour chat ID is: {chat_id}")
                    print("Please update config/telegram_config.json manually")
            else:
                print("\n📝 Multiple chat IDs found. Please choose the correct one")
                print("and update config/telegram_config.json with your chat ID")
        else:
            print("\n❌ No messages found!")
            print("\nMake sure you have:")
            print(f"1. Started a chat with @{bot_username}")
            print("2. Sent at least one message to the bot")
            print("3. Sent the message recently (within last 24 hours)")
    else:
        print("\n❌ Could not retrieve messages from Telegram")
        print("Please check your internet connection and try again")

if __name__ == "__main__":
    main()