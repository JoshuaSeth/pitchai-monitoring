# Copyright (c) 2026 PitchAI. All rights reserved.
"""Unchanged existing dispatcher runner payload, not locally executed."""

CODEX_CONFIG_TOML = """
# Service Monitoring: Codex escalation config (runner container).
approval_policy = "never"
sandbox_mode = "danger-full-access"
hide_agent_reasoning = true
""".lstrip()


DOCKER_CLI_INSTALL_PRE_COMMAND = (
    "command -v docker >/dev/null 2>&1 && exit 0\n"
    "echo '[pre] docker CLI missing; attempting install' >&2\n"
    "if command -v apt-get >/dev/null 2>&1; then\n"
    "  apt-get update >&2\n"
    "  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends docker.io >&2\n"
    "  rm -rf /var/lib/apt/lists/*\n"
    "  exit 0\n"
    "fi\n"
    "if command -v apk >/dev/null 2>&1; then\n"
    "  apk add --no-cache docker-cli >&2\n"
    "  exit 0\n"
    "fi\n"
    "echo '[pre] No supported package manager found to install docker CLI' >&2\n"
    "exit 0\n"
)
