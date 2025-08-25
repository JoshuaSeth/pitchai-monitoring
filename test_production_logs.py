#!/usr/bin/env python3
"""
Demo script for the Production Log Collection Module

This script demonstrates the safe, non-invasive production log collection
capabilities. All operations are READ-ONLY and completely safe.

Run with: python test_production_logs.py
"""

def main():
    print("🚀 Production Log Collection Module Demo")
    print("=" * 50)
    print("This module provides SAFE, READ-ONLY access to production Docker logs")
    print("✅ Automatically loads .env file")
    print("✅ SSH-based secure remote access")
    print("✅ Only safe Docker commands allowed")
    print("✅ No modifications to running containers")
    print()
    
    try:
        from monitoring.production_logs import LogInterface
        
        interface = LogInterface()
        
        print("1. 🏥 Health Check...")
        healthy = interface.check_health()
        print(f"   System healthy: {'✅' if healthy else '❌'}")
        
        print("\n2. 📦 Container Discovery...")
        containers = interface.get_containers()
        print(f"   Found {len(containers)} running containers:")
        for i, container in enumerate(containers[:5], 1):  # Show first 5
            print(f"     {i}. {container}")
        if len(containers) > 5:
            print(f"     ... and {len(containers) - 5} more")
        
        print("\n3. 🚨 Error Check (last hour)...")
        errors = interface.get_recent_errors(hours=1)
        total_errors = sum(len(logs) for logs in errors.values())
        print(f"   Found {total_errors} error entries")
        if total_errors == 0:
            print("   ✅ No errors detected!")
        
        print("\n4. 📊 Quick Stats...")
        logs = interface.get_recent_logs(hours=1)
        total_logs = sum(len(container_logs) for container_logs in logs.values())
        print(f"   Total log entries (last hour): {total_logs}")
        print(f"   Containers with activity: {len([c for c, l in logs.items() if l])}")
        
        print("\n✅ Demo completed successfully!")
        print("\n🔧 Available CLI Commands:")
        print("   python -m monitoring.production_logs.cli status")
        print("   python -m monitoring.production_logs.cli health")
        print("   python -m monitoring.production_logs.cli errors")
        print("   python -m monitoring.production_logs.cli logs 2")
        print("   python -m monitoring.production_logs.cli save 4")
        
        print("\n🐍 Python Interface Example:")
        print("   from monitoring.production_logs import LogInterface")
        print("   interface = LogInterface()")
        print("   logs = interface.get_recent_logs(hours=2)")
        print("   errors = interface.get_recent_errors(hours=1)")
        print("   filepath = interface.save_all_logs(hours=4)")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nPlease ensure:")
        print("- You have a .env file with HETZNER credentials")
        print("- Network access to the production server")
        print("- Required Python packages are installed")


if __name__ == "__main__":
    main()