#!/usr/bin/env python3
"""
Telegram Bot Launcher - Choose which bot functionality to start
"""

import os
import sys


def main():
    print("="*60)
    print("🤖 TELEGRAM BOT LAUNCHER")
    print("="*60)
    print("\nChoose a bot to start:\n")
    print("1. Claude Command Bot - Execute Claude CLI via Telegram")
    print("2. Message Server - Listen and respond to messages")
    print("3. Test Notifications - Send test notifications")
    print("4. Get Chat ID - Helper to find your chat ID")
    print("5. Exit")
    print()

    choice = input("Enter choice (1-5): ").strip()

    if choice == "1":
        print("\n🚀 Starting Claude Command Bot...")
        print("Send messages to @pitchai_dev_bot to execute Claude commands")
        print("-"*60)
        from claude_telegram_bot import main as claude_main
        claude_main()

    elif choice == "2":
        print("\n📡 Starting Message Server...")
        from telegram_bot_server import TelegramBotServer
        bot = TelegramBotServer()
        bot.run()

    elif choice == "3":
        print("\n📤 Sending Test Notifications...")
        from verify_telegram_integration import main as verify_main
        verify_main()

    elif choice == "4":
        print("\n🔍 Getting Chat ID...")
        from get_telegram_chat_id import main as chat_id_main
        chat_id_main()

    elif choice == "5":
        print("\n👋 Goodbye!")
        sys.exit(0)

    else:
        print("\n❌ Invalid choice")
        sys.exit(1)

if __name__ == "__main__":
    # Add current directory to path for imports
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Launcher stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
