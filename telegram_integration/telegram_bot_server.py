#!/usr/bin/env python3
"""
Telegram Bot Server - Listens for incoming messages and responds
"""

import signal
import sys
import time
from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

class TelegramBotServer:
    def __init__(self):
        self.running = True
        self.last_update_id = None
        self.message_count = 0

    def send_message(self, chat_id, text):
        """Send a message to a chat"""
        url = f"{BASE_URL}/sendMessage"
        data = {"chat_id": chat_id, "text": text}
        response = requests.post(url, json=data)
        return response.json()

    def get_updates(self, offset=None, timeout=30):
        """Get updates using long polling"""
        url = f"{BASE_URL}/getUpdates"
        params = {"timeout": timeout}
        if offset:
            params["offset"] = offset

        try:
            response = requests.get(url, params=params, timeout=timeout+5)
            return response.json()
        except requests.exceptions.Timeout:
            return {"ok": True, "result": []}
        except Exception as e:
            print(f"❌ Error getting updates: {e}")
            return {"ok": False, "result": []}

    def process_message(self, message):
        """Process an incoming message"""
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        from_user = message["from"]
        username = from_user.get("username", "Unknown")
        first_name = from_user.get("first_name", "")

        self.message_count += 1

        # Print the received message
        print("\n" + "="*60)
        print(f"📨 INCOMING MESSAGE #{self.message_count}")
        print(f"From: {first_name} (@{username})")
        print(f"Chat ID: {chat_id}")
        print(f"Text: {text}")
        print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        print("="*60)

        # Process commands
        response_text = self.handle_command(text)

        # Send response
        if response_text:
            print("📤 Sending response...")
            result = self.send_message(chat_id, response_text)
            if result.get("ok"):
                print("✅ Response sent successfully")
            else:
                print(f"❌ Failed to send response: {result}")

    def handle_command(self, text):
        """Handle different commands"""
        text_lower = text.lower().strip()

        if text_lower == "/start":
            return "🤖 Welcome to AutoPAR Bot!\n\nAvailable commands:\n/status - Check bot status\n/backlog - Show backlog info\n/help - Show this help\n/test - Run a test"

        elif text_lower == "/status":
            return f"✅ Bot is running!\n\n📊 Stats:\n• Messages received: {self.message_count}\n• Uptime: Active\n• Time: {datetime.now().strftime('%H:%M:%S')}"

        elif text_lower == "/backlog":
            return "📋 Backlog Processing:\n\nUse these commands to manage backlog:\n• python run_backlog.py test --telegram\n• python run_backlog.py real --project autopar --telegram\n\nNotifications will be sent here!"

        elif text_lower == "/test":
            return f"🧪 Test successful!\n\nThis is a test response from the bot.\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        elif text_lower == "/help":
            return "📚 Help:\n\n/status - Check bot status\n/backlog - Backlog processing info\n/test - Run a test\n/help - Show this help\n\nJust type any message and I'll echo it back!"

        elif text_lower.startswith("/"):
            return f"❓ Unknown command: {text}\n\nType /help for available commands"

        else:
            # Echo the message back
            return f"📝 You said: {text}\n\n(I received your message at {datetime.now().strftime('%H:%M:%S')})"

    def run(self):
        """Main bot loop"""
        print("🤖 Telegram Bot Server Starting...")
        print(f"Bot Token: {BOT_TOKEN[:20]}...")
        print("="*60)

        # Get bot info
        bot_info_url = f"{BASE_URL}/getMe"
        response = requests.get(bot_info_url)
        if response.json().get("ok"):
            bot_data = response.json()["result"]
            print(f"✅ Bot: @{bot_data['username']} ({bot_data['first_name']})")
            print(f"✅ Bot ID: {bot_data['id']}")
        else:
            print("❌ Failed to get bot info")
            return

        print("="*60)
        print("📡 Listening for messages...")
        print("Send a message to @pitchai_dev_bot to test!")
        print("Press Ctrl+C to stop")
        print("="*60)

        while self.running:
            try:
                # Get updates with long polling
                updates = self.get_updates(offset=self.last_update_id, timeout=30)

                if updates.get("ok"):
                    for update in updates["result"]:
                        update_id = update["update_id"]

                        # Update the offset
                        if self.last_update_id is None or update_id > self.last_update_id:
                            self.last_update_id = update_id + 1

                        # Process message if it exists
                        if "message" in update:
                            self.process_message(update["message"])

            except KeyboardInterrupt:
                print("\n\n🛑 Stopping bot server...")
                self.running = False
                break
            except Exception as e:
                print(f"❌ Error in main loop: {e}")
                time.sleep(5)

        print("👋 Bot server stopped")

    def stop(self):
        """Stop the bot server"""
        self.running = False

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Interrupt received, stopping...")
    sys.exit(0)

if __name__ == "__main__":
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # Create and run bot
    bot = TelegramBotServer()

    try:
        bot.run()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
    finally:
        print("✅ Bot server terminated")
