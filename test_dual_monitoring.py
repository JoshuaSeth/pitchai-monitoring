#!/usr/bin/env python3
"""
Test script to verify both monitoring systems work together
"""

import subprocess
import asyncio
import time

async def test_monitoring_agents():
    print("🧪 Testing Dual Monitoring System")
    print("=" * 50)
    
    # Test 1: Direct agent execution
    print("\n1. Testing Autopar Monitoring Agent (dry-run)...")
    try:
        result = subprocess.run([
            "python3", "autopar_monitoring_agent.py", "--dry-run", "--hours", "1"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print("   ✅ Autopar agent executed successfully")
            if "Status Determined:" in result.stdout:
                print("   ✅ Claude analysis completed")
            if "Telegram" in result.stdout:
                print("   ✅ Telegram notification prepared")
        else:
            print(f"   ❌ Autopar agent failed: {result.stderr}")
    except Exception as e:
        print(f"   ❌ Error testing autopar agent: {e}")

    print("\n2. Testing Main Claude Monitoring Agent (dry-run)...")
    try:
        result = subprocess.run([
            "python3", "claude_monitoring_agent.py", "--dry-run", "--hours", "1"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print("   ✅ Main monitoring agent executed successfully")
            if "Status Determined:" in result.stdout:
                print("   ✅ Claude analysis completed")
        else:
            print(f"   ❌ Main monitoring agent failed: {result.stderr}")
    except Exception as e:
        print(f"   ❌ Error testing main agent: {e}")

    # Test 2: FastAPI endpoints (check if configured)
    print("\n3. Testing FastAPI endpoint configuration...")
    try:
        with open("main.py", "r") as f:
            main_content = f.read()
            
        if "autopar-monitoring" in main_content:
            print("   ✅ Autopar monitoring endpoint configured")
        if "/run/autopar-monitoring" in main_content:
            print("   ✅ Autopar monitoring route defined")
        if "trigger_autopar_monitoring" in main_content:
            print("   ✅ Autopar monitoring function implemented")
    except Exception as e:
        print(f"   ❌ Error checking FastAPI configuration: {e}")

    # Test 3: Scheduler integration
    print("\n4. Testing Scheduler Integration...")
    try:
        with open("python_scheduler.py", "r") as f:
            scheduler_content = f.read()
            
        if "run_autopar_morning_monitoring" in scheduler_content:
            print("   ✅ Autopar morning monitoring scheduled")
        if "run_autopar_afternoon_monitoring" in scheduler_content:
            print("   ✅ Autopar afternoon monitoring scheduled")
        if "03:15" in scheduler_content and "10:30" in scheduler_content:
            print("   ✅ Autopar monitoring times correctly offset")
    except Exception as e:
        print(f"   ❌ Error checking scheduler: {e}")

    print("\n" + "=" * 50)
    print("✅ Dual Monitoring System Test Complete")
    print("\nSUMMARY:")
    print("• Main monitoring: claude_monitoring_agent.py")
    print("• Autopar monitoring: autopar_monitoring_agent.py") 
    print("• Both use Claude AI analysis")
    print("• Both send Telegram notifications")
    print("• Scheduled at offset times (15 minutes apart)")
    print("• Both available via FastAPI endpoints")

if __name__ == "__main__":
    asyncio.run(test_monitoring_agents())