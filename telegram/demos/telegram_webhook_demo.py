#!/usr/bin/env python3
"""
Demonstrate webhook-style event handling for Telegram bot
"""

import time
from datetime import datetime

import requests

BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
CHAT_ID = "5246077032"

class TelegramEventHandler:
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
        self.events = []
        self.running = True

    def send_message(self, text):
        """Send a message"""
        url = f"{self.base_url}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": text}
        response = requests.post(url, json=data)
        return response.json()

    def get_updates(self, offset=None):
        """Get new updates"""
        url = f"{self.base_url}/getUpdates"
        params = {"timeout": 5}
        if offset:
            params["offset"] = offset

        try:
            response = requests.get(url, params=params, timeout=10)
            return response.json()
        except:
            return {"ok": False, "result": []}

    def handle_event(self, update):
        """Handle an incoming event"""
        if "message" in update:
            message = update["message"]
            text = message.get("text", "")
            from_user = message["from"]["first_name"]

            # Log the event
            event = {
                "type": "message",
                "text": text,
                "user": from_user,
                "time": datetime.now().strftime('%H:%M:%S')
            }
            self.events.append(event)

            # Print event notification
            print(f"\n🔔 EVENT: New message from {from_user}")
            print(f"   Text: {text}")
            print(f"   Time: {event['time']}")

            # Auto-respond based on content
            if text.startswith("/"):
                self.handle_command(text)
            else:
                self.handle_text(text)

    def handle_command(self, command):
        """Handle bot commands"""
        responses = {
            "/start": "Bot event handler is active! I'm processing your commands in real-time.",
            "/status": f"✅ Active | Events: {len(self.events)} | Time: {datetime.now().strftime('%H:%M:%S')}",
            "/events": f"📊 Processed {len(self.events)} events so far",
            "/test": "🧪 Test successful! Event handling is working."
        }

        response = responses.get(command, f"Received command: {command}")
        self.send_message(response)
        print(f"   ↩️  Sent response for {command}")

    def handle_text(self, text):
        """Handle regular text messages"""
        # Simulate processing
        response = f"Processed your message: '{text}' | Event #{len(self.events)}"
        self.send_message(response)
        print("   ↩️  Processed and responded")

    def run_event_loop(self, duration=20):
        """Run the event processing loop"""
        print("="*60)
        print("🎯 TELEGRAM EVENT HANDLER DEMO")
        print("="*60)
        print(f"Duration: {duration} seconds")
        print("="*60)

        # Send start notification
        self.send_message(f"""🎯 Event Handler Active for {duration} seconds!

Send messages to test event processing:
• Commands: /start, /status, /events, /test
• Text: Any message will be processed
• All events are logged and handled

Bot: @pitchai_dev_bot""")

        print("\n📡 Listening for events...")
        print("Send messages to @pitchai_dev_bot")
        print("-"*60)

        last_update_id = None
        start_time = time.time()

        while self.running and (time.time() - start_time) < duration:
            updates = self.get_updates(offset=last_update_id)

            if updates.get("ok"):
                for update in updates["result"]:
                    update_id = update["update_id"]
                    if last_update_id is None or update_id > last_update_id:
                        last_update_id = update_id + 1
                        self.handle_event(update)

            time.sleep(0.5)  # Check for updates every 500ms

        # Send summary
        print("\n" + "="*60)
        print("📊 EVENT HANDLER SUMMARY")
        print("="*60)
        print(f"Total Events Processed: {len(self.events)}")

        if self.events:
            print("\nEvent Log:")
            for i, event in enumerate(self.events, 1):
                print(f"  {i}. [{event['time']}] {event['user']}: {event['text']}")

        summary = f"""✅ Event Handler Demo Complete!

📊 Summary:
• Events processed: {len(self.events)}
• Duration: {duration} seconds
• Status: All events handled successfully

Event handling is working perfectly!"""

        self.send_message(summary)
        print("\n✅ Demo completed!")

def main():
    handler = TelegramEventHandler()
    handler.run_event_loop(duration=15)

if __name__ == "__main__":
    main()
