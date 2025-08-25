#!/bin/bash
# Wrapper script for Claude CLI using uv environment
cd /app
exec uv run python claude_cli_wrapper.py "$@"