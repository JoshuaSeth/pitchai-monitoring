# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the official Claude ``/usage`` readout per profile, fail-closed.

The pinned binary reads its own login and prints plan limits without a model
turn. This stdlib-only module (the host runs it with Python 3.10) spawns it with
a scrubbed environment in an empty directory, kills it at a deadline, and
disables all further probing through a guard file when a result is not provably
local. The exporter itself never opens credential files.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .claude_quota import carried_quota, guard_reason, number_value, object_value, parse_limits

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .timeseries_types import JsonObject, JsonValue

DEFAULT_GUARD_FILE = Path("/var/lib/pitchai-codex-usage/claude-usage-probe.disabled")
DEFAULT_INTERVAL_SECONDS, DEFAULT_TIMEOUT_SECONDS, DEFAULT_BUDGET_SECONDS = 300.0, 60.0, 120.0
POLL_SECONDS, GUARD_DIRECTORY_MODE, MAX_OUTPUT_BYTES = 0.05, 0o700, 1 << 20
USAGE_ARGUMENTS = ("-p", "/usage", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config")
SAFE_ENVIRONMENT = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
RUN_ERRORS = {"failed": "probe_failed", "timeout": "probe_timeout", "unavailable": "binary_unavailable"}


@dataclass(frozen=True)
class CliRun:
    """One finished official-CLI invocation: ``ok``, ``failed``, ``timeout`` or ``unavailable``."""

    outcome: str
    stdout: str


def _wait(process_id: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while True:
        finished, status = os.waitpid(process_id, os.WNOHANG)
        if finished:
            return "ok" if os.waitstatus_to_exitcode(status) == 0 else "failed"
        if time.monotonic() >= deadline:
            with suppress(OSError):
                os.killpg(process_id, signal.SIGKILL)
            os.waitpid(process_id, 0)
            return "timeout"
        time.sleep(POLL_SECONDS)


def run_cli(arguments: tuple[str, ...], environment: Mapping[str, str], directory: Path, timeout: float) -> CliRun:
    """Return the outcome and output of one official-CLI command run in its own process group."""
    previous_directory = Path.cwd()
    outcome, text = "unavailable", ""
    with tempfile.TemporaryFile() as capture:
        actions = [
            (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
            (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0),
            (os.POSIX_SPAWN_DUP2, capture.fileno(), 1),
        ]
        process_id: int | None = None
        with suppress(OSError):
            os.chdir(directory)
            process_id = os.posix_spawn(arguments[0], arguments, environment, file_actions=actions, setsid=True)
        with suppress(OSError):
            os.chdir(previous_directory)
        if process_id is not None:
            outcome = _wait(process_id, timeout)
            capture.seek(0)
            text = capture.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    return CliRun(outcome, text if outcome == "ok" else "")


def _decode(text: str) -> tuple[bool, JsonValue]:
    lines = text.strip().splitlines()
    for candidate in (text, lines[-1] if lines else ""):
        with suppress(ValueError):
            return True, cast("JsonValue", json.loads(candidate))
    return False, None


@dataclass(frozen=True)
class QuotaSettings:
    """Previous snapshot rows by id, safety guard file, and probe cadence, deadline and run budget."""

    previous: Mapping[str, JsonValue]
    guard: Path = DEFAULT_GUARD_FILE
    interval: float = DEFAULT_INTERVAL_SECONDS
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    budget: float = DEFAULT_BUDGET_SECONDS


class QuotaProbe:
    """Read each profile's plan limits at most once per interval; one unsafe result disables probing."""

    binary: Path
    settings: QuotaSettings
    started: float
    disabled: bool

    def __init__(self, binary: Path, settings: QuotaSettings) -> None:
        """Bind the pinned binary; an existing (or unreadable) guard file keeps probing disabled."""
        self.binary, self.settings, self.started, self.disabled = binary, settings, time.monotonic(), True
        with suppress(OSError):
            self.disabled = settings.guard.exists()

    def reading(self, row_id: str, home: Path, *, now: float) -> JsonObject:
        """Return a fresh reading when due, otherwise the carried previous reading."""
        carried = carried_quota(self.settings.previous.get(row_id))
        if self.disabled:
            return {**carried, "quota_error": "probe_disabled"}
        attempted = number_value(carried["quota_attempted_at"])
        recent = attempted is not None and 0 <= now - attempted < self.settings.interval
        if recent or time.monotonic() - self.started >= self.settings.budget:
            return carried
        error, windows, scoped = self.probe(home, now)
        if error is not None:
            return {**carried, "quota_attempted_at": now, "quota_error": error}
        fresh: JsonObject = {"windows": windows, "scoped_windows": scoped, "quota_observed_at": now}
        return {**carried, **fresh, "quota_attempted_at": now, "quota_error": None}

    def probe(self, home: Path, now: float) -> tuple[str | None, JsonObject, list[JsonValue]]:
        """Return ``(error, windows, scoped)`` from one readout, retried once without the traffic flag."""
        if self.disabled:
            return "probe_disabled", {}, []
        arguments = (str(self.binary), *USAGE_ARGUMENTS, "--setting-sources", "user")
        for quiet in (True, False):
            environment = {**SAFE_ENVIRONMENT, "HOME": str(home), "TZ": "UTC", "DISABLE_AUTOUPDATER": "1"}
            if quiet:
                environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
            with tempfile.TemporaryDirectory(prefix="claude-usage-", ignore_cleanup_errors=True) as directory:
                run = run_cli(arguments, environment, Path(directory), self.settings.timeout)
            decoded, document = _decode(run.stdout)
            if run.outcome != "ok" or not decoded:
                return RUN_ERRORS.get(run.outcome, "probe_failed"), {}, []
            reason = guard_reason(document)
            if reason is not None:
                self._trip(reason, now)
                return "probe_guard_tripped", {}, []
            windows, scoped = parse_limits(str(object_value(document).get("result") or ""), now)
            if windows or scoped:
                return None, windows, scoped
        return "no_limits_reported", {}, []

    def _trip(self, reason: str, now: float) -> None:
        self.disabled = True
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        with suppress(OSError):
            self.settings.guard.parent.mkdir(parents=True, exist_ok=True, mode=GUARD_DIRECTORY_MODE)
            self.settings.guard.write_text(f"{stamp} {reason}; remove after review to re-enable\n", encoding="utf-8")
        sys.stderr.write(f"Claude usage probe disabled: {reason}\n")
