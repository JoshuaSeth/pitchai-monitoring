# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define a strictly typed mutable namespace for guardian CLI parsing."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TypedDict

DEFAULT_AUDIT_DB = Path("/var/lib/pitchai-auth-reset-guardian/audit.sqlite3")
_MAX_EVENT_QUERY_LIMIT = 10_000


class CliValues(TypedDict):
    """Store parser values behind typed namespace properties."""

    audit_db: Path
    lock_wait_seconds: float
    command: str
    simulate: Path | None
    now: str | None
    dry_run: bool
    no_notify: bool
    require_notifier: bool
    account_label: str
    expires_at: str
    reason: str
    limit: int


class CliArguments(argparse.Namespace):
    """Describe the complete argument namespace produced by this CLI."""

    def __init__(self) -> None:
        """Initialize every subcommand field with its parser-neutral default."""
        super().__init__()
        self._values: CliValues = {
            "audit_db": DEFAULT_AUDIT_DB,
            "lock_wait_seconds": 0.0,
            "command": "",
            "simulate": None,
            "now": None,
            "dry_run": False,
            "no_notify": False,
            "require_notifier": False,
            "account_label": "",
            "expires_at": "",
            "reason": "",
            "limit": 100,
        }

    @property
    def audit_db(self) -> Path:
        """Return the selected audit database path."""
        return self._values["audit_db"]

    @audit_db.setter
    def audit_db(self, value: Path) -> None:
        self._values["audit_db"] = value

    @property
    def lock_wait_seconds(self) -> float:
        """Return the bounded process-lock wait duration."""
        return self._values["lock_wait_seconds"]

    @lock_wait_seconds.setter
    def lock_wait_seconds(self, value: float) -> None:
        self._values["lock_wait_seconds"] = value

    @property
    def command(self) -> str:
        """Return the selected subcommand."""
        return self._values["command"]

    @command.setter
    def command(self, value: str) -> None:
        self._values["command"] = value

    @property
    def simulate(self) -> Path | None:
        """Return the optional simulation fixture path."""
        return self._values["simulate"]

    @simulate.setter
    def simulate(self, value: Path | None) -> None:
        self._values["simulate"] = value

    @property
    def now(self) -> str | None:
        """Return the optional simulation clock override."""
        return self._values["now"]

    @now.setter
    def now(self, value: str | None) -> None:
        self._values["now"] = value

    @property
    def dry_run(self) -> bool:
        """Return whether mutation is suppressed."""
        return self._values["dry_run"]

    @dry_run.setter
    def dry_run(self, value: bool) -> None:
        self._values["dry_run"] = value

    @property
    def no_notify(self) -> bool:
        """Return whether notifications are disabled."""
        return self._values["no_notify"]

    @no_notify.setter
    def no_notify(self, value: bool) -> None:
        self._values["no_notify"] = value

    @property
    def require_notifier(self) -> bool:
        """Return whether live notification availability is mandatory."""
        return self._values["require_notifier"]

    @require_notifier.setter
    def require_notifier(self, value: bool) -> None:
        self._values["require_notifier"] = value

    @property
    def account_label(self) -> str:
        """Return the manual account label."""
        return self._values["account_label"]

    @account_label.setter
    def account_label(self, value: str) -> None:
        self._values["account_label"] = value

    @property
    def expires_at(self) -> str:
        """Return the manual expiry selector."""
        return self._values["expires_at"]

    @expires_at.setter
    def expires_at(self, value: str) -> None:
        self._values["expires_at"] = value

    @property
    def reason(self) -> str:
        """Return the manual redemption reason."""
        return self._values["reason"]

    @reason.setter
    def reason(self, value: str) -> None:
        self._values["reason"] = value

    @property
    def limit(self) -> int:
        """Return the recent-event query limit."""
        return self._values["limit"]

    @limit.setter
    def limit(self, value: int) -> None:
        self._values["limit"] = value

    def is_locked_command(self) -> bool:
        """Return whether this subcommand mutates the audit log."""
        return self.command in {"run", "manual-redeem"}

    def events_limit_is_valid(self) -> bool:
        """Return whether the requested event page satisfies its safety bound."""
        return 1 <= self.limit <= _MAX_EVENT_QUERY_LIMIT
