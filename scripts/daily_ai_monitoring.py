#!/usr/bin/env python3
"""
Daily AI Monitoring Script for PitchAI

This script is designed to be run daily by cron within the Docker container
to execute the complete monitoring workflow:
1. Run UI tests on monitoring.pitchai.net
2. Collect logs from all Docker containers
3. Analyze results and detect issues
4. Generate incidents for critical problems
5. Send Telegram notifications with daily report
"""

import sys
import os

# Add the monitoring package to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.ai_agent import DailyOrchestrator


def main():
    """Main entry point for daily monitoring."""
    print("🤖 Starting PitchAI Daily AI Monitoring...")
    print(f"⏰ Execution time: {__import__('datetime').datetime.utcnow().isoformat()}")
    print("📍 Production environment: monitoring.pitchai.net")
    print("")
    
    try:
        # Execute daily monitoring
        DailyOrchestrator.run()
        print("✅ Daily monitoring completed successfully!")
        
    except Exception as e:
        print(f"❌ Daily monitoring failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()