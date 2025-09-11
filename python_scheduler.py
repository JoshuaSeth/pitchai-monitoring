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
    """Run morning monitoring at 04:00 UTC (05:00 Amsterdam time)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running morning monitoring via Python scheduler")
    try:
        subprocess.run(["python", "claude_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Morning monitoring error: {e}")

def run_afternoon_monitoring():
    """Run afternoon monitoring at 11:00 UTC (12:00 Amsterdam time)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running afternoon monitoring via Python scheduler")
    try:
        subprocess.run(["python", "claude_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Afternoon monitoring error: {e}")

def run_autopar_morning_monitoring():
    """Run autopar staging monitoring at 04:15 UTC (05:15 Amsterdam time - 15 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running autopar staging monitoring via Python scheduler")
    try:
        subprocess.run(["python", "autopar_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Autopar monitoring error: {e}")

def run_autopar_afternoon_monitoring():
    """Run autopar afternoon monitoring at 11:15 UTC (12:15 Amsterdam time - 15 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running autopar afternoon monitoring via Python scheduler")
    try:
        subprocess.run(["python", "autopar_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Autopar afternoon monitoring error: {e}")

def run_quickchat_morning_monitoring():
    """Run quickchat monitoring at 04:30 UTC (05:30 Amsterdam time - 30 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running quickchat monitoring via Python scheduler")
    try:
        subprocess.run(["python", "quickchat_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Quickchat monitoring error: {e}")

def run_quickchat_afternoon_monitoring():
    """Run quickchat monitoring at 11:30 UTC (12:30 Amsterdam time - 30 minutes after main monitoring)"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] Running quickchat afternoon monitoring via Python scheduler")
    try:
        subprocess.run(["python", "quickchat_monitoring_agent.py"], timeout=3600)
    except Exception as e:
        print(f"[{timestamp}] Quickchat afternoon monitoring error: {e}")

def scheduler_thread():
    """Run scheduler in background thread"""
    print("🐍 Starting Python scheduler thread")
    
    # Schedule monitoring jobs (Amsterdam time: 05:00 & 12:00)
    schedule.every().day.at("04:00").do(run_morning_monitoring)
    schedule.every().day.at("11:00").do(run_afternoon_monitoring)
    
    # Schedule autopar-specific monitoring jobs (offset by 15 minutes)
    schedule.every().day.at("04:15").do(run_autopar_morning_monitoring)
    schedule.every().day.at("11:15").do(run_autopar_afternoon_monitoring)
    
    # Schedule quickchat monitoring jobs (offset by 30 minutes)
    schedule.every().day.at("04:30").do(run_quickchat_morning_monitoring)
    schedule.every().day.at("11:30").do(run_quickchat_afternoon_monitoring)
    
    # Send initial message
    message = f"🚀 <b>PYTHON SCHEDULER STARTED</b>\n\n"
    message += f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    message += f"✅ Scheduler initialized\n"
    message += f"📋 Scheduled jobs (Amsterdam time):\n"
    message += f"  • Main monitoring: 04:00 UTC (05:00 Amsterdam)\n"
    message += f"  • Main monitoring: 11:00 UTC (12:00 Amsterdam)\n"
    message += f"  • Autopar monitoring: 04:15 UTC (05:15 Amsterdam)\n"
    message += f"  • Autopar monitoring: 11:15 UTC (12:15 Amsterdam)\n"
    message += f"  • Quickchat monitoring: 04:30 UTC (05:30 Amsterdam)\n"
    message += f"  • Quickchat monitoring: 11:30 UTC (12:30 Amsterdam)\n"
    
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