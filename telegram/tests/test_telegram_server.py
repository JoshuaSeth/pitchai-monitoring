#!/usr/bin/env python3
"""
Test the Telegram bot server by sending a message and checking response
"""

from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"

def send_test_message(text):
    """Send a test message to the bot"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    response = requests.post(url, json=data)
    return response.json()

def test_bot_interaction():
    """Test sending messages and getting responses"""
    print("="*60)
    print("🧪 TELEGRAM BOT SERVER TEST")
    print("="*60)

    # First, notify that we're starting the test
    print("\n📤 Sending notification to Telegram...")
    notification = f"🔄 Bot server test starting at {datetime.now().strftime('%H:%M:%S')}\n\nThe bot will now listen for your messages.\nTry sending:\n• /status\n• /help\n• /test\n• Any text message"

    result = send_test_message(notification)
    if result.get("ok"):
        print(f"✅ Notification sent (Message ID: {result['result']['message_id']})")
    else:
        print(f"❌ Failed to send notification: {result}")

    print("\n" + "="*60)
    print("📡 Starting bot server to listen for messages...")
    print("="*60)
    print("\n⚡ The bot is now LIVE and listening!")
    print("📱 Open Telegram and send a message to @pitchai_dev_bot")
    print("💬 Try commands like: /status, /help, /test")
    print("🛑 Press Ctrl+C to stop the server\n")

    # Import and run the bot server
    try:
        from telegram_bot_server import TelegramBotServer
        bot = TelegramBotServer()
        bot.run()
    except KeyboardInterrupt:
        print("\n✅ Test completed")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_bot_interaction()
