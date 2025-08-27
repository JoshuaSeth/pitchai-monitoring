#!/usr/bin/env python3
"""
Python-based scheduler as alternative to cron
Runs scheduled jobs in background threads
"""
import threading
import time
import schedule
from datetime import datetime
from telegram_sync_helper import send_telegram_message_sync
import subprocess
import os

def run_morning_monitoring():
    """Run morning monitoring at 03:00 UTC"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running morning monitoring via Python scheduler")
    try:
        subprocess.run(["python", "claude_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Morning monitoring error: {e}")

def run_afternoon_monitoring():
    """Run afternoon monitoring at 10:15 UTC"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running afternoon monitoring via Python scheduler")
    try:
        subprocess.run(["python", "claude_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Afternoon monitoring error: {e}")

def scheduler_thread():
    """Run scheduler in background thread"""
    print("🐍 Starting Python scheduler thread")
    
    # Schedule monitoring jobs
    schedule.every().day.at("03:00").do(run_morning_monitoring)
    schedule.every().day.at("10:15").do(run_afternoon_monitoring)
    
    # Send initial message
    message = f"🚀 <b>PYTHON SCHEDULER STARTED</b>\n\n"
    message += f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    message += f"✅ Scheduler initialized\n"
    message += f"📋 Scheduled jobs:\n"
    message += f"  • Morning report: 03:00 UTC\n"
    message += f"  • Afternoon report: 10:15 UTC\n"
    
    try:
        send_telegram_message_sync(message)
    except Exception as e:
        print(f"Failed to send startup message: {e}")
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)  # Check every 30 seconds
        except Exception as e:
            print(f"Scheduler error: {e}")
            time.sleep(60)

def start_scheduler():
    """Start the scheduler in a daemon thread"""
    thread = threading.Thread(target=scheduler_thread, daemon=True)
    thread.start()
    print("✅ Python scheduler thread started")
    return thread

if __name__ == "__main__":
    # For testing - run scheduler in foreground
    scheduler_thread()