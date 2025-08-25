#!/usr/bin/env python3
"""
Telegram Helper Module for Monitoring Agent

Simple wrapper around the existing TelegramNotifier class for easy integration
with the Claude monitoring agent.
"""

import asyncio
import os
import re
from pathlib import Path


def load_environment():
    """Load environment variables from .env file if it exists."""
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"\'')

def get_telegram_config() -> tuple[str, str]:
    """Get Telegram bot token and chat ID from environment."""
    load_environment()  # Ensure .env file is loaded
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID environment variable not set")

    return bot_token, chat_id


def convert_markdown_to_html(text: str) -> str:
    """
    Convert markdown formatting to HTML entities for Telegram.

    Supports:
    - **bold** -> <b>bold</b>
    - *italic* -> <i>italic</i>
    - `code` -> <code>code</code>
    - ```code blocks``` -> <pre>code blocks</pre>
    - ~~strikethrough~~ -> <s>strikethrough</s>

    Args:
        text (str): Text with markdown formatting

    Returns:
        str: Text with HTML entities
    """
    # Handle code blocks first (triple backticks)
    text = re.sub(r'```([^`]+)```', r'<pre>\1</pre>', text, flags=re.MULTILINE | re.DOTALL)

    # Handle inline code (single backticks)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Handle bold (**text**)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

    # Handle italic (*text*) - but not if it's part of bold
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)

    # Handle strikethrough (~~text~~)
    text = re.sub(r'~~([^~]+)~~', r'<s>\1</s>', text)

    # Escape any remaining HTML characters that aren't our tags
    # First, protect our tags
    protected_tags = []
    tag_pattern = r'</?(?:b|i|code|pre|s)>'

    def protect_tag(match):
        tag = match.group(0)
        placeholder = f"__PROTECTED_TAG_{len(protected_tags)}__"
        protected_tags.append(tag)
        return placeholder

    text = re.sub(tag_pattern, protect_tag, text)

    # Escape HTML characters
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # Restore protected tags
    for i, tag in enumerate(protected_tags):
        text = text.replace(f"__PROTECTED_TAG_{i}__", tag)

    return text


async def send_telegram_message(message: str, parse_mode: str = None, auto_convert: bool = True) -> bool:
    """
    Send a message via Telegram using the existing TelegramNotifier.

    Args:
        message (str): The message to send
        parse_mode (str): Parsing mode ('Markdown' or 'HTML'). If None and auto_convert=True, uses HTML
        auto_convert (bool): If True, automatically convert markdown to HTML entities

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        from telegram_integration.telegram_notifier import TelegramNotifier

        bot_token, chat_id = get_telegram_config()

        # Auto-convert markdown to HTML if enabled
        if auto_convert and (parse_mode is None or parse_mode.upper() == 'HTML'):
            message = convert_markdown_to_html(message)
            parse_mode = 'HTML'

        notifier = TelegramNotifier(bot_token)
        result = notifier.send_formatted_message(chat_id, message, parse_mode)

        print(f"  ✅ Telegram message sent (Message ID: {result.get('message_id', 'unknown')})")
        return True

    except Exception as e:
        print(f"  ❌ Failed to send Telegram message: {e}")
        return False


async def send_monitoring_alert(title: str, details: str, severity: str = "INFO") -> bool:
    """
    Send a formatted monitoring alert via Telegram.

    Args:
        title (str): Alert title
        details (str): Alert details
        severity (str): Severity level (INFO, WARNING, ERROR, CRITICAL)

    Returns:
        bool: True if successful, False otherwise
    """
    severity_emojis = {
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🚨"
    }

    emoji = severity_emojis.get(severity.upper(), "📋")

    formatted_message = f"""{emoji} **MONITORING ALERT - {severity.upper()}**

**{title}**

{details}

_Automated alert from Claude Monitoring Agent_"""

    return await send_telegram_message(formatted_message)


if __name__ == "__main__":
    """Test the Telegram helper functionality."""

    async def test_telegram_helper():
        print("🧪 Testing Telegram Helper")
        print("=" * 30)

        # Test basic message
        print("Testing basic message...")
        success1 = await send_telegram_message("🤖 Test message from Telegram Helper")

        # Test monitoring alert
        print("Testing monitoring alert...")
        success2 = await send_monitoring_alert(
            "System Health Check",
            "All systems are operating normally. This is a test alert.",
            "INFO"
        )

        if success1 and success2:
            print("✅ All tests passed!")
        else:
            print("❌ Some tests failed!")

    asyncio.run(test_telegram_helper())
