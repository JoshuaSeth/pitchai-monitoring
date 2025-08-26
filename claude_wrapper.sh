#!/bin/bash
# Working Claude CLI wrapper using official Claude Code API
cd /app
exec uv run python claude_api_wrapper.py "$@"