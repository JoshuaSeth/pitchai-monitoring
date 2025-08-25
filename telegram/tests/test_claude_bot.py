#!/usr/bin/env python3
"""
Quick test of the Claude Telegram bot
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time

from telegram.claude_telegram_bot import ClaudeTelegramBot


def test_claude_bot():
    """Test the Claude bot for 5 seconds"""
    print("="*60)
    print("🧪 TESTING CLAUDE TELEGRAM BOT")
    print("="*60)

    # Create bot instance
    bot = ClaudeTelegramBot()

    # Send test notification
    bot.send_message(
        bot.CHAT_ID if hasattr(bot, 'CHAT_ID') else "5246077032",
        "🧪 Claude Bot Test - 5 second demo\n\nSend me a message like:\n• `List files`\n• `claude: hello`\n• `/status`"
    )

    # Run for 5 seconds
    def stop_after_timeout():
        time.sleep(5)
        bot.running = False
        print("\n⏰ Test timeout reached")

    timeout_thread = threading.Thread(target=stop_after_timeout)
    timeout_thread.daemon = True
    timeout_thread.start()

    # Run the bot
    print("Bot running for 5 seconds...")
    print("Send a message to @pitchai_dev_bot to test")
    print("-"*60)

    # Start bot (will run for 5 seconds)
    try:
        # Just check connection, don't run full loop
        updates = bot.get_updates(timeout=2)
        if updates.get("ok"):
            print("✅ Bot connected successfully")
            print(f"✅ Commands executed: {bot.commands_executed}")
            print(f"✅ Project path: {bot.project_path}")
        else:
            print("❌ Failed to connect")
    except Exception as e:
        print(f"Error: {e}")

    print("\n✅ Claude bot test complete!")

if __name__ == "__main__":
    test_claude_bot()
