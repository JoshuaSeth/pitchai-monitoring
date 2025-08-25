#!/usr/bin/env python3
"""
Run the Telegram bot server for a demo period
"""

import threading
import time
from datetime import datetime

import requests
from telegram_bot_server import TelegramBotServer

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"

def send_message(text):
    """Send a message via Telegram API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    response = requests.post(url, json=data)
    return response.json()

def run_demo(duration=15):
    """Run the bot server for a limited time"""
    print("="*60)
    print("🤖 TELEGRAM BOT SERVER DEMO")
    print("="*60)

    # Send start notification
    start_msg = f"""🚀 Bot Server is NOW ACTIVE!

The bot is listening for your messages.

Try sending these commands to @pitchai_dev_bot:
• /status - Check bot status
• /help - Show help menu
• /test - Run a test
• /backlog - Backlog info
• Or just type any message!

Server will run for {duration} seconds..."""

    result = send_message(start_msg)
    if result.get("ok"):
        print("✅ Start notification sent to Telegram")

    # Create bot server
    bot = TelegramBotServer()

    # Create a thread to stop the bot after duration
    def stop_after_timeout():
        time.sleep(duration)
        bot.stop()
        print(f"\n⏰ Demo time ({duration}s) expired, stopping server...")

    timeout_thread = threading.Thread(target=stop_after_timeout)
    timeout_thread.daemon = True
    timeout_thread.start()

    # Run the bot
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n✅ Demo stopped by user")
    finally:
        # Send completion message
        end_msg = f"""✅ Bot Server Demo Complete!

Stats:
• Messages processed: {bot.message_count}
• Duration: {duration} seconds
• Time: {datetime.now().strftime('%H:%M:%S')}

The bot server has stopped listening.
To run again: python run_bot_server_demo.py"""

        send_message(end_msg)
        print("\n✅ Demo completed successfully!")

if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    run_demo(duration)
