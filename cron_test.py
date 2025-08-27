#!/usr/bin/env python3
"""
Simple cron test that sends a Telegram message
"""
import os
from datetime import datetime
from telegram_sync_helper import send_telegram_message_sync

def send_test_message():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    message = f"🔔 <b>CRON TEST MESSAGE</b>\n\n"
    message += f"📅 Time: {timestamp}\n"
    message += f"✅ Cron job is working!\n"
    message += f"🤖 This is an automated test from the monitoring system.\n"
    message += f"🔧 PID: {os.getpid()}\n"
    
    print(f"[{timestamp}] Sending cron test message to Telegram")
    
    try:
        success = send_telegram_message_sync(message)
        if success:
            print(f"[{timestamp}] ✅ Cron test message sent successfully")
        else:
            print(f"[{timestamp}] ❌ Failed to send cron test message")
        return success
    except Exception as e:
        print(f"[{timestamp}] ❌ Error: {e}")
        return False

if __name__ == "__main__":
    send_test_message()