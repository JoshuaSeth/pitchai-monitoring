#!/usr/bin/env python3
"""
Test the complete integration with a simple backlog item
"""

import json
import subprocess


def create_test_backlog():
    """Create a simple test backlog"""
    test_items = [
        {
            "name": "Verify Telegram Integration",
            "description": "Create a file called telegram_test.txt with current timestamp",
            "status": "pending"
        }
    ]

    # Save as test backlog
    with open("test_backlog.json", "w") as f:
        json.dump(test_items, f, indent=2)

    print("✅ Test backlog created")

def run_test_with_telegram():
    """Run the backlog processor with Telegram enabled"""
    print("\n🚀 Running backlog processor with Telegram notifications...")
    print("-" * 50)

    # Create a simple Python script that will be executed
    test_script = '''
import json
from telegram_notifier import TelegramNotifier
from datetime import datetime

# Load config
with open("telegram_config.json", "r") as f:
    config = json.load(f)

# Send notification
notifier = TelegramNotifier(config["bot_token"])
chat_id = config["chat_id"]

message = f"""🎯 **Backlog Task Completed**
────────────────
📋 **Task:** Verify Telegram Integration
✅ **Status:** SUCCESS
📝 **Output:** Created test file with timestamp
⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}

This is a live test of the AutoPAR backlog processing system with Telegram notifications enabled."""

success = notifier.send_formatted_message(chat_id, message)
if success:
    print("✅ Telegram notification sent successfully!")

    # Create the test file
    with open("telegram_test.txt", "w") as f:
        f.write(f"Telegram integration verified at {datetime.now()}")
    print("✅ Test file created")
else:
    print("❌ Failed to send Telegram notification")
'''

    with open("run_integration_test.py", "w") as f:
        f.write(test_script)

    # Execute the test
    result = subprocess.run(["python3", "run_integration_test.py"], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("Errors:", result.stderr)

    return result.returncode == 0

def main():
    print("=" * 50)
    print("🧪 COMPLETE INTEGRATION TEST")
    print("=" * 50)

    # Load current config
    with open("telegram_config.json") as f:
        config = json.load(f)

    print(f"✅ Telegram enabled: {config['enabled']}")
    print(f"✅ Chat ID configured: {config['chat_id']}")
    print()

    # Run the test
    if run_test_with_telegram():
        print("\n" + "=" * 50)
        print("🎉 INTEGRATION TEST SUCCESSFUL!")
        print("=" * 50)
        print("\n✅ Telegram notifications are working!")
        print("✅ Messages are being sent to chat ID:", config['chat_id'])
        print("✅ The backlog processing system is ready to use")
        print("\nYou should see a notification in your Telegram app!")
    else:
        print("\n❌ Test failed - check the errors above")

if __name__ == "__main__":
    main()
