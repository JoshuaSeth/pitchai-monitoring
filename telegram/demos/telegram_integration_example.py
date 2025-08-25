#!/usr/bin/env python3
"""
Example integration of TelegramNotifier with the backlog processing system.

This demonstrates how to use the TelegramNotifier to send notifications
when backlog tasks are completed.
"""

import json
from datetime import datetime

from telegram_notifier import TelegramNotifier

# Configuration
BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"
# You'll need to get your chat ID by messaging the bot first
CHAT_ID = None  # Replace with your actual chat ID after messaging the bot

def send_backlog_completion_update(completed_tasks, project_name="autopar"):
    """
    Send a Telegram notification for completed backlog tasks.

    Args:
        completed_tasks (list): List of completed task dictionaries
        project_name (str): Name of the project
    """
    if not CHAT_ID:
        print("⚠️ CHAT_ID not configured. Please set your chat ID first.")
        print("Run telegram_notifier.py to get your chat ID.")
        return

    try:
        notifier = TelegramNotifier(BOT_TOKEN)
        result = notifier.send_backlog_completion_notification(
            CHAT_ID, completed_tasks, project_name
        )
        print(f"✅ Telegram notification sent successfully! Message ID: {result.get('message_id')}")

    except Exception as e:
        print(f"❌ Failed to send Telegram notification: {str(e)}")

def load_and_notify_backlog_results(project_name="autopar"):
    """
    Load backlog results from JSON file and send Telegram notification.

    Args:
        project_name (str): Name of the project
    """
    try:
        # Load results from the file created by process_backlog.py
        with open(f"backlog_results_{project_name}.json") as f:
            results = json.load(f)

        # Filter only successful tasks
        completed_tasks = [r for r in results if r.get('success', False)]

        if completed_tasks:
            send_backlog_completion_update(completed_tasks, project_name)
        else:
            print("No successful tasks found to notify about.")

    except FileNotFoundError:
        print(f"❌ No backlog results file found for project: {project_name}")
        print("Run process_backlog.py first to generate results.")
    except json.JSONDecodeError:
        print("❌ Invalid JSON in backlog results file.")
    except Exception as e:
        print(f"❌ Error loading backlog results: {str(e)}")

def demo_notification():
    """
    Send a demo notification with sample tasks.
    """
    sample_tasks = [
        {
            "name": "Create Telegram integration module",
            "success": True,
            "timestamp": datetime.now().isoformat()
        },
        {
            "name": "Add comprehensive error handling",
            "success": True,
            "timestamp": datetime.now().isoformat()
        },
        {
            "name": "Write documentation and examples",
            "success": True,
            "timestamp": datetime.now().isoformat()
        }
    ]

    send_backlog_completion_update(sample_tasks, "Todo Management System")

if __name__ == "__main__":
    print("🔗 Telegram Integration Example")
    print("=" * 50)

    # First, get chat ID if not set
    if not CHAT_ID:
        print("⚠️ Chat ID not configured!")
        print("1. Message the bot @pitchai_dev_bot on Telegram")
        print("2. Run: python telegram_notifier.py")
        print("3. Copy your chat ID and update CHAT_ID in this file")
        print("4. Run this script again")
    else:
        print(f"📱 Using chat ID: {CHAT_ID}")

        # Demo notification
        print("\n📤 Sending demo notification...")
        demo_notification()

        # Try to load and send actual backlog results
        print("\n📋 Checking for actual backlog results...")
        load_and_notify_backlog_results()
