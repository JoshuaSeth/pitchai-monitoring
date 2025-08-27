#!/usr/bin/env python3
"""
Synchronous wrapper for Telegram messaging
Used by cron jobs and schedulers that can't handle async
"""
import asyncio
from telegram_helper import send_telegram_message as async_send_telegram_message

def send_telegram_message_sync(message: str) -> bool:
    """
    Synchronous wrapper for async Telegram message sending.
    
    Args:
        message: The message to send (HTML formatted)
        
    Returns:
        bool: True if message was sent successfully
    """
    try:
        # Create new event loop for synchronous context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Run the async function
            result = loop.run_until_complete(async_send_telegram_message(message))
            return result
        finally:
            loop.close()
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return False