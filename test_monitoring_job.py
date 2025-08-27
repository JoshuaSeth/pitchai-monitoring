#!/usr/bin/env python3
"""
Minimal test monitoring job that actually works
"""
import json
import os
import requests
from datetime import datetime
from telegram_helper import send_telegram_message

def run_test_monitoring():
    """Simple test monitoring job that collects basic info and sends to Telegram"""
    
    print(f"[{datetime.now()}] Starting test monitoring job")
    
    # Collect basic system info
    report = {
        "timestamp": datetime.now().isoformat(),
        "type": "TEST_MONITORING",
        "checks": []
    }
    
    # Check 1: Container count
    try:
        import subprocess
        result = subprocess.run(["docker", "ps", "--format", "json"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            containers = [json.loads(line) for line in result.stdout.strip().split('\n') if line]
            report["checks"].append({
                "name": "Docker Containers",
                "status": "✅ PASS",
                "value": f"{len(containers)} containers running"
            })
        else:
            report["checks"].append({
                "name": "Docker Containers", 
                "status": "❌ FAIL",
                "error": result.stderr
            })
    except Exception as e:
        report["checks"].append({
            "name": "Docker Containers",
            "status": "⚠️ ERROR", 
            "error": str(e)
        })
    
    # Check 2: Disk space
    try:
        result = subprocess.run(["df", "-h", "/"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 5:
                    usage = parts[4].rstrip('%')
                    status = "✅ PASS" if int(usage) < 80 else "⚠️ WARNING" if int(usage) < 90 else "❌ CRITICAL"
                    report["checks"].append({
                        "name": "Disk Space",
                        "status": status,
                        "value": f"{usage}% used"
                    })
    except Exception as e:
        report["checks"].append({
            "name": "Disk Space",
            "status": "⚠️ ERROR",
            "error": str(e)
        })
    
    # Check 3: Memory usage
    try:
        result = subprocess.run(["free", "-m"], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 3:
                    total = int(parts[1])
                    used = int(parts[2])
                    usage_pct = int((used / total) * 100)
                    status = "✅ PASS" if usage_pct < 80 else "⚠️ WARNING" if usage_pct < 90 else "❌ CRITICAL"
                    report["checks"].append({
                        "name": "Memory Usage",
                        "status": status,
                        "value": f"{usage_pct}% used ({used}MB / {total}MB)"
                    })
    except Exception as e:
        report["checks"].append({
            "name": "Memory Usage", 
            "status": "⚠️ ERROR",
            "error": str(e)
        })
    
    # Format message for Telegram
    message = f"🧪 <b>TEST MONITORING REPORT</b>\n"
    message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    
    for check in report["checks"]:
        message += f"{check['status']} <b>{check['name']}</b>\n"
        if 'value' in check:
            message += f"   └─ {check['value']}\n"
        elif 'error' in check:
            message += f"   └─ Error: {check.get('error', 'Unknown')[:100]}\n"
        message += "\n"
    
    # Determine overall status
    has_critical = any('❌' in check.get('status', '') for check in report["checks"])
    has_warning = any('⚠️' in check.get('status', '') for check in report["checks"])
    
    if has_critical:
        message += "📊 <b>Overall Status: CRITICAL ISSUES DETECTED</b>"
    elif has_warning:
        message += "📊 <b>Overall Status: WARNINGS DETECTED</b>"
    else:
        message += "📊 <b>Overall Status: ALL SYSTEMS OPERATIONAL</b>"
    
    print(f"[{datetime.now()}] Sending Telegram notification")
    
    # Send to Telegram
    try:
        success = send_telegram_message(message)
        if success:
            print(f"[{datetime.now()}] ✅ Test monitoring completed and sent to Telegram")
        else:
            print(f"[{datetime.now()}] ❌ Test monitoring completed but Telegram send failed")
        return success
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Error sending to Telegram: {e}")
        return False

if __name__ == "__main__":
    success = run_test_monitoring()
    exit(0 if success else 1)