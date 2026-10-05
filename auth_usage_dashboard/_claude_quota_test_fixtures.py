# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures for the Claude ``/usage`` plan-limit readout tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ._timeseries_test_fixtures import UsageTimeSeriesCase
from .claude_accounts import collect
from .claude_probe import QuotaSettings

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject, JsonValue

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC).timestamp()
SESSION_RESET = datetime(2026, 10, 5, 13, 49, tzinfo=UTC).timestamp()
WEEK_RESET = datetime(2026, 10, 10, 3, 59, tzinfo=UTC).timestamp()
FABLE_RESET = datetime(2026, 10, 10, 4, 0, tzinfo=UTC).timestamp()
DOT = "\xb7"
LIMITS_TEXT = "\n".join((
    "You are currently using your subscription to power your Claude Code usage",
    "",
    f"Current session: 34% used {DOT} resets Oct 5, 1:49pm (UTC)",
    f"Current week (all models): 11% used {DOT} resets Oct 10, 3:59am (UTC)",
    f"Current week (Fable): 0% used {DOT} resets Oct 10, 4am (UTC)",
    "",
    "What's contributing to your limits usage?",
    "Current weekly spend: 12% used",
))
NO_LIMITS_TEXT = "You are currently using your subscription to power your Claude Code usage\n"
PROBE_ARGUMENTS = "-p /usage --output-format json --no-session-persistence --strict-mcp-config --setting-sources user"
PROFILES = ("primary", "secondary")
FAKE_CLI_SCRIPT = """#!/bin/sh
if [ "$1" = "auth" ]; then
  printf 'auth\\n' >> "$HOME/calls.log"
  printf '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty",'\\
' "subscriptionType": "max", "email": "%s@pitchai.net", "apiKeySource": null}\\n' "$(basename "$HOME")"
  exit 0
fi
printf 'usage quiet=%s tz=%s updater=%s key=%s entries=%s args=%s\\n' \\
  "${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-unset}" "${TZ:-unset}" "${DISABLE_AUTOUPDATER:-unset}" \\
  "${ANTHROPIC_API_KEY:-unset}" "$(ls -A | wc -l | tr -d ' ')" "$*" >> "$HOME/calls.log"
printf '%s\\n' "$PWD" >> "$HOME/directories.log"
[ -f "$HOME/sleep" ] && sleep 30
[ -f "$HOME/exit" ] && exit 3
reply="$HOME/reply-${CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC:-retry}.json"
[ -f "$reply" ] || reply="$HOME/reply.json"
cat "$reply"
"""


def usage_reply(text: str, **overrides: JsonValue) -> JsonObject:
    """Return one official ``/usage`` JSON result, optionally with unsafe overrides."""
    counts: JsonObject = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "server_tool_use": {"web_search_requests": 0},
    }
    document: JsonObject = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 0,
        "local_command": "usage",
        "total_cost_usd": 0,
        "usage": counts,
        "result": text,
    }
    return {**document, **overrides}


class ClaudeQuotaCase(UsageTimeSeriesCase):
    """Provide one fake official binary and one two-profile owner in an isolated root."""

    def fake_cli(self) -> Path:
        """Return the path of one stand-in for the official binary that records each call."""
        path = self.root / "runtime" / "claude"
        path.parent.mkdir(exist_ok=True)
        path.write_text(FAKE_CLI_SCRIPT, encoding="utf-8")
        path.chmod(0o755)
        return path

    def owners(self) -> Path:
        """Return the owners root holding one fresh owner with the primary and secondary profiles."""
        state = self.root / "claude-owners" / "test-owner"
        principal: JsonObject = {"provider": "claude_code", "tenant_id": "tenant", "user_id": "person"}
        profiles: list[JsonValue] = [{"id": profile, "home": profile} for profile in PROFILES]
        for profile in PROFILES:
            (state / profile).mkdir(parents=True, exist_ok=True)
        documents: dict[str, JsonObject] = {
            "owner.json": principal,
            "accounts.json": {**principal, "accounts": profiles},
            "health.json": {"writtenAt": NOW, "accounts": []},
        }
        for name, document in documents.items():
            (state / name).write_text(json.dumps(document), encoding="utf-8")
        return state.parent

    def home(self, profile: str) -> Path:
        """Return the private HOME of one profile, created on first use."""
        home = self.root / "claude-owners" / "test-owner" / profile
        home.mkdir(parents=True, exist_ok=True)
        return home

    def reply(self, profile: str, document: JsonObject | str, attempt: str = "") -> None:
        """Make the fake binary print one reply; ``1`` and ``retry`` select one attempt only."""
        name = f"reply-{attempt}.json" if attempt else "reply.json"
        text = document if isinstance(document, str) else json.dumps(document)
        (self.home(profile) / name).write_text(text, encoding="utf-8")

    def calls(self, profile: str) -> list[str]:
        """Return the binary calls one profile has seen, oldest first."""
        log = self.home(profile) / "calls.log"
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []

    def settings(self, previous: dict[str, JsonValue] | None = None, *, timeout: float = 20.0) -> QuotaSettings:
        """Return probe settings that keep the guard file inside the isolated root."""
        return QuotaSettings(previous or {}, guard=self.root / "guard" / "probe.disabled", timeout=timeout)

    def collect_rows(self, settings: QuotaSettings, *, now: float = NOW) -> list[JsonObject]:
        """Return the exported rows of one collection with the fake binary."""
        document = collect(self.owners(), self.fake_cli(), now=now, quota=settings)
        rows = document["accounts"]
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
