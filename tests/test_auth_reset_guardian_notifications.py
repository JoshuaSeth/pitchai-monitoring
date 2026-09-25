# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock requester-private guardian notification behavior."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, final

import pytest

from auth_reset_guardian.guardian import (
    Alert,
    CommandNotifier,
    NotificationError,
    alert_batches,
)
from auth_reset_guardian.process_types import ProcessResult
from domain_checks.testing import verify

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from auth_reset_guardian.process_types import ProcessOptions

MAXIMUM_ALERT_MESSAGE_LENGTH = 3_800


@final
class ReceiptRunner:
    """Return one requester-private receipt at the subprocess boundary."""

    def __init__(self, receipt: str) -> None:
        """Store the receipt returned by the child double."""
        self.receipt = receipt

    def __call__(
        self,
        command: Sequence[str],
        options: ProcessOptions,
    ) -> ProcessResult:
        """Validate notifier isolation and return a completed child result.

        Returns:
            The resulting value.

        """
        verify(options.timeout_seconds > 0)
        verify(options.capture_limit > 0)
        verify(options.env)
        return self.completed_process(command)

    def completed_process(
        self,
        args: Sequence[str],
    ) -> ProcessResult:
        """Build the typed successful child result.

        Returns:
            The resulting value.

        """
        _ = args
        return ProcessResult(
            returncode=0,
            stdout=self.receipt,
            stderr="",
        )


def test_command_notifier_requires_verified_requester_private_receipt() -> None:
    """Reject a notifier receipt unless it proves requester-private routing."""
    private_receipt = json.dumps(
        {
            "status": "sent",
            "policy": "personal-first",
            "route_kind": "private",
            "requester_key": "seth-ori",
            "destination_ref": "seth-ori",
        },
    )
    CommandNotifier(
        ["telegram-helper"],
        runner=ReceiptRunner(private_receipt),
    ).notify("safe message")

    broad_receipt = private_receipt.replace('"private"', '"group"')
    with pytest.raises(NotificationError) as captured:
        CommandNotifier(
            ["telegram-helper"],
            runner=ReceiptRunner(broad_receipt),
        ).notify("must fail closed")
    verify(captured.value.error_code == "invalid_private_receipt")


def test_command_notifier_child_does_not_inherit_broker_or_openai_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Strip broker and OpenAI secrets from notifier child environments."""
    secret_names = (
        "AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN",
        "AUTH_TOKEN_SERVER_ADMIN_TOKEN",
        "AUTH_TOKEN_SERVER_ADMIN_TOKEN_ALIASES",
        "AUTH_TOKEN_SERVER_CLIENT_TOKEN",
        "AUTH_TOKEN_SERVER_CLIENT_TOKEN_ALIASES",
        "OPENAI_API_KEY",
    )
    for name in secret_names:
        monkeypatch.setenv(name, f"secret-{name.lower()}")
    receipt = {
        "status": "sent",
        "policy": "personal-first",
        "route_kind": "private",
        "requester_key": "seth-ori",
        "destination_ref": "seth-ori",
    }
    child_code = (
        "import json, os\n"
        f"names = {secret_names!r}\n"
        "if any(os.environ.get(name) for name in names):\n"
        "    raise RuntimeError('secret inherited')\n"
        f"print(json.dumps({receipt!r}))\n"
    )

    shell_marker = tmp_path / "shell-expanded"
    shell_like_message = f"$(touch {shell_marker})"
    descriptor_count = _open_descriptor_count()
    CommandNotifier([sys.executable, "-c", child_code]).notify(shell_like_message)
    verify(not shell_marker.exists())
    verify(_open_descriptor_count() == descriptor_count)


def test_command_notifier_bounds_both_child_output_streams() -> None:
    """Fail loudly after draining oversized stdout and stderr without deadlock."""
    oversized_bytes = 70_000
    child_code = f"import sys; sys.stdout.write('x' * {oversized_bytes}); sys.stderr.write('y' * {oversized_bytes})"

    with pytest.raises(NotificationError) as captured:
        CommandNotifier(
            [sys.executable, "-c", child_code],
            require_private_receipt=False,
        ).notify("bounded output")
    verify(captured.value.error_code == "output_too_large")


def test_command_notifier_kills_and_reaps_timed_out_child(tmp_path: Path) -> None:
    """Kill and reap a timed-out child so no zombie remains."""
    pid_path = tmp_path / "timed-out-child.pid"
    child_code = (
        f"import os, pathlib, time; pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    with pytest.raises(NotificationError) as captured:
        CommandNotifier(
            [sys.executable, "-c", child_code],
            timeout_seconds=0.5,
            require_private_receipt=False,
        ).notify("time out")
    verify(captured.value.error_code == "timeout")
    child_pid = int(pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ChildProcessError):
        _ = os.waitpid(child_pid, os.WNOHANG)


def _open_descriptor_count() -> int:
    """Count descriptors currently owned by the test process.

    Returns:
        The current open-descriptor count.

    """
    with os.scandir("/proc/self/fd") as entries:
        return sum(1 for _entry in entries)


def test_alert_batches_never_mark_unreported_overflow_as_sent() -> None:
    """Preserve every alert identity when message limits require batching."""
    alert_indexes = range(100)
    alert_line = "x" * 100
    alerts = [Alert(key=f"alert-{index}", line=alert_line) for index in alert_indexes]
    batches = alert_batches(alerts)
    verify(len(batches) > 1)

    actual_keys: list[str] = []
    for batch in batches:
        actual_keys.extend(alert.key for alert in batch)
    expected_keys = [alert.key for alert in alerts]
    verify(actual_keys == expected_keys)

    for batch in batches:
        message_lines = ["<b>Codex reset guardian</b>"]
        message_lines.extend(alert.line for alert in batch)
        verify(len("\n".join(message_lines)) <= MAXIMUM_ALERT_MESSAGE_LENGTH)
