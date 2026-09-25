# Copyright (c) 2026 PitchAI. All rights reserved.
"""Immutable runner configuration for monitor dispatcher escalations."""

from __future__ import annotations

CODEX_CONFIG_TOML = """
# Service Monitoring: Codex escalation config (runner container).
approval_policy = "never"
sandbox_mode = "danger-full-access"
hide_agent_reasoning = true
""".lstrip()

DOCKER_PRE_COMMAND = """command -v docker >/dev/null 2>&1 && exit 0
echo '[pre] docker CLI missing; attempting install' >&2
if command -v apt-get >/dev/null 2>&1; then
  apt-get update >&2
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker.io >&2
  rm -rf /var/lib/apt/lists/*
  exit 0
fi
if command -v apk >/dev/null 2>&1; then
  apk add --no-cache docker-cli >&2
  exit 0
fi
echo '[pre] No supported package manager found to install docker CLI' >&2
exit 0
"""
