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

def run_autopar_morning_monitoring():
    """Run autopar staging monitoring at 03:15 UTC (15 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running autopar staging monitoring via Python scheduler")
    try:
        subprocess.run(["python", "autopar_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Autopar monitoring error: {e}")

def run_autopar_afternoon_monitoring():
    """Run autopar staging monitoring at 10:30 UTC (15 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running autopar afternoon monitoring via Python scheduler")
    try:
        subprocess.run(["python", "autopar_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Autopar afternoon monitoring error: {e}")

def scheduler_thread():
    """Run scheduler in background thread"""
    print("🐍 Starting Python scheduler thread")
    
    # Schedule monitoring jobs
    schedule.every().day.at("03:00").do(run_morning_monitoring)
    schedule.every().day.at("10:15").do(run_afternoon_monitoring)
    
    # Schedule autopar-specific monitoring jobs (offset by 15 minutes)
    schedule.every().day.at("03:15").do(run_autopar_morning_monitoring)
    schedule.every().day.at("10:30").do(run_autopar_afternoon_monitoring)
    
    # Send initial message
    message = f"🚀 <b>PYTHON SCHEDULER STARTED</b>\n\n"
    message += f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    message += f"✅ Scheduler initialized\n"
    message += f"📋 Scheduled jobs:\n"
    message += f"  • Main monitoring: 03:00 UTC\n"
    message += f"  • Main monitoring: 10:15 UTC\n"
    message += f"  • Autopar monitoring: 03:15 UTC\n"
    message += f"  • Autopar monitoring: 10:30 UTC\n"
    
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