#!/usr/bin/env python3
"""
Telegram Bot Notifier Module

This module provides a TelegramNotifier class for integrating with Telegram bots.
It handles sending messages, getting updates, and sending backlog completion notifications.
"""

import json
from datetime import datetime
from typing import Any

import requests


class TelegramNotifier:
    """
    A class to handle Telegram bot operations including sending messages and notifications.
    """

    def __init__(self, bot_token: str):
        """
        Initialize the TelegramNotifier with a bot token.

        Args:
            bot_token (str): The Telegram bot token from BotFather
        """
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })

    def _make_request(self, method: str, params: dict | None = None) -> dict[str, Any]:
        """
        Make a request to the Telegram Bot API.

        Args:
            method (str): The API method to call
            params (dict, optional): Parameters to send with the request

        Returns:
            dict: The response from the Telegram API

        Raises:
            Exception: If the API request fails
        """
        url = f"{self.base_url}/{method}"

        try:
            if params:
                response = self.session.post(url, json=params)
            else:
                response = self.session.get(url)

            response.raise_for_status()
            data = response.json()

            if not data.get('ok'):
                error_description = data.get('description', 'Unknown error')
                raise Exception(f"Telegram API error: {error_description}")

            return data

        except requests.exceptions.RequestException as e:
            raise Exception(f"HTTP request failed: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON response: {str(e)}")

    def get_bot_info(self) -> dict[str, Any]:
        """
        Get information about the bot.

        Returns:
            dict: Bot information including username, first_name, etc.
        """
        response = self._make_request('getMe')
        return response['result']

    def send_message(self, chat_id: str, text: str, parse_mode: str | None = None) -> dict[str, Any]:
        """
        Send a plain text message to a chat.

        Args:
            chat_id (str): The chat ID to send the message to
            text (str): The message text to send
            parse_mode (str, optional): Message parsing mode ('Markdown' or 'HTML')

        Returns:
            dict: Information about the sent message
        """
        params = {
            'chat_id': chat_id,
            'text': text
        }

        if parse_mode:
            params['parse_mode'] = parse_mode

        response = self._make_request('sendMessage', params)
        return response['result']

    def send_formatted_message(self, chat_id: str, text: str, parse_mode: str = 'Markdown') -> dict[str, Any]:
        """
        Send a formatted message with Markdown or HTML support.

        Args:
            chat_id (str): The chat ID to send the message to
            text (str): The formatted message text
            parse_mode (str): Parsing mode ('Markdown' or 'HTML'), defaults to 'Markdown'

        Returns:
            dict: Information about the sent message
        """
        return self.send_message(chat_id, text, parse_mode)

    def get_updates(self, offset: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get updates from the bot to find chat IDs and messages.

        Args:
            offset (int, optional): Identifier of the first update to return
            limit (int): Number of updates to retrieve (1-100)

        Returns:
            list: List of update objects
        """
        params = {'limit': limit}

        if offset is not None:
            params['offset'] = offset

        response = self._make_request('getUpdates', params)
        return response['result']

    def send_backlog_completion_notification(self, chat_id: str, completed_tasks: list[dict],
                                           project_name: str = "Project") -> dict[str, Any]:
        """
        Send a notification about completed backlog tasks with details.

        Args:
            chat_id (str): The chat ID to send the notification to
            completed_tasks (list): List of completed task dictionaries
            project_name (str): Name of the project

        Returns:
            dict: Information about the sent message
        """
        if not completed_tasks:
            message = f"🎯 *{project_name} Backlog Update*\n\nNo tasks were completed in this run."
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            message = f"🎯 *{project_name} Backlog Completion Report*\n"
            message += f"📅 *Completed:* {timestamp}\n"
            message += f"✅ *Tasks Completed:* {len(completed_tasks)}\n\n"

            for i, task in enumerate(completed_tasks[:10], 1):  # Limit to first 10 tasks
                task_name = task.get('name', task.get('task', 'Unknown Task'))
                success = task.get('success', True)
                status_emoji = "✅" if success else "❌"

                # Truncate long task names
                if len(task_name) > 50:
                    task_name = task_name[:47] + "..."

                message += f"{status_emoji} *{i}.* {task_name}\n"

            if len(completed_tasks) > 10:
                message += f"\n... and {len(completed_tasks) - 10} more tasks\n"

            message += f"\n🚀 *Total Progress:* {len(completed_tasks)} tasks completed!"

        return self.send_formatted_message(chat_id, message, 'Markdown')

    def get_chat_ids_from_updates(self) -> list[dict[str, Any]]:
        """
        Helper method to extract chat IDs from recent updates.

        Returns:
            list: List of dictionaries with chat information
        """
        updates = self.get_updates()
        chat_info = []
        seen_chats = set()

        for update in updates:
            message = update.get('message', {})
            chat = message.get('chat', {})

            if chat and chat.get('id') not in seen_chats:
                chat_info.append({
                    'chat_id': chat.get('id'),
                    'type': chat.get('type'),
                    'title': chat.get('title'),
                    'first_name': chat.get('first_name'),
                    'last_name': chat.get('last_name'),
                    'username': chat.get('username')
                })
                seen_chats.add(chat.get('id'))

        return chat_info


def main():
    """
    Test script to verify Telegram bot functionality.
    """
    # Bot token
    BOT_TOKEN = "8268321313:AAH6a-i0A0fxmt7jtXoQ5_PtucT0YwTk8BI"

    print("🤖 Telegram Bot Test Script")
    print("=" * 50)

    try:
        # Initialize the notifier
        notifier = TelegramNotifier(BOT_TOKEN)
        print("✅ TelegramNotifier initialized successfully")

        # Get bot info
        print("\n📋 Getting bot information...")
        bot_info = notifier.get_bot_info()
        print(f"✅ Bot Name: {bot_info.get('first_name')}")
        print(f"✅ Bot Username: @{bot_info.get('username')}")
        print(f"✅ Bot ID: {bot_info.get('id')}")

        # Get updates to find chat IDs
        print("\n🔍 Checking for recent messages...")
        chat_ids = notifier.get_chat_ids_from_updates()

        if chat_ids:
            print(f"✅ Found {len(chat_ids)} chat(s):")
            for chat in chat_ids:
                chat_type = chat.get('type', 'unknown')
                if chat_type == 'private':
                    name = f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
                    username = chat.get('username')
                    identifier = f"@{username}" if username else name
                    print(f"   • Private chat with {identifier} (ID: {chat.get('chat_id')})")
                else:
                    title = chat.get('title', 'Unknown Group')
                    print(f"   • {chat_type.title()} chat: {title} (ID: {chat.get('chat_id')})")

            # Try sending a test message to the first chat
            test_chat_id = str(chat_ids[0]['chat_id'])
            print(f"\n📤 Sending test message to chat ID: {test_chat_id}")

            test_message = "🤖 *Telegram Bot Test*\n\nThis is a test message to verify the bot is working correctly!"
            message_info = notifier.send_formatted_message(test_chat_id, test_message)
            print(f"✅ Test message sent successfully! Message ID: {message_info.get('message_id')}")

            # Test backlog notification
            print("\n📋 Sending sample backlog completion notification...")
            sample_tasks = [
                {"name": "Create Telegram integration module", "success": True},
                {"name": "Add error handling and logging", "success": True},
                {"name": "Write comprehensive tests", "success": True}
            ]

            notifier.send_backlog_completion_notification(
                test_chat_id,
                sample_tasks,
                "Todo Management System"
            )
            print("✅ Backlog notification sent successfully!")

        else:
            print("❌ No chat messages found!")
            print("\n📋 To get your chat ID:")
            print("1. Start a chat with your bot by searching for its username in Telegram")
            print(f"2. Send any message to @{bot_info.get('username')}")
            print("3. Run this script again to see your chat ID")

        print("\n🎉 All tests completed successfully!")

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        print("\n🔧 Troubleshooting:")
        print("1. Check that the bot token is correct")
        print("2. Make sure the bot is not blocked")
        print("3. Verify internet connectivity")
        return False

    return True


if __name__ == "__main__":
    main()
