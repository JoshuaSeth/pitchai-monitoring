#!/bin/bash

# Start Claude Telegram Bot
# This bot listens for Telegram messages and executes Claude commands

echo "🤖 Starting Claude Telegram Bot..."
echo "=================================="
echo "Bot: @pitchai_dev_bot"
echo "=================================="
echo ""

# Check if Claude CLI is installed
if ! command -v claude &> /dev/null; then
    echo "❌ Claude CLI not found!"
    echo "Please install Claude CLI first"
    exit 1
fi

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

# Change to parent directory (todos)
cd "$PARENT_DIR"

# Start the bot
python3 telegram/claude_telegram_bot.py "$@"