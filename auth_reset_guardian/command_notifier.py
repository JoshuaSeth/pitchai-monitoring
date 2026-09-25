# Copyright (c) 2026 PitchAI. All rights reserved.
"""Deliver one guardian notification through a reviewed child command."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .json_contract import decode_json
from .process_boundary import run_process
from .process_types import (
    ProcessOptions,
    ProcessOutputLimitError,
    ProcessTimeoutError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .process_types import ProcessRunner

_MAX_NOTIFICATION_OUTPUT_BYTES = 64 * 1024


class NotificationError(RuntimeError):
    """Report one sanitized notification-delivery failure."""

    def __init__(self, error_code: str):
        """Initialize this instance."""
        super().__init__(f"notification failed ({error_code})")
        self.error_code: str = error_code


class CommandNotifier:
    """Invoke a reviewed command without a shell and validate its receipt."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 30.0,
        require_private_receipt: bool = True,
        runner: ProcessRunner = run_process,
    ):
        """Initialize this instance.

        Raises:
            ValueError: If a value violates the required contract.

        """
        if not command:
            msg = "notification command must not be empty"
            raise ValueError(msg)
        self.command: tuple[str, ...] = tuple(command)
        self.timeout_seconds: float = timeout_seconds
        self.require_private_receipt: bool = require_private_receipt
        self._runner: ProcessRunner = runner

    def notify(self, message: str) -> None:
        """Deliver one message or raise a sanitized notification error.

        Raises:
            NotificationError: If private notification delivery cannot be verified.

        """
        child_environment = {
            "HOME": os.environ.get("HOME", "/root"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PATH": os.defpath,
        }
        try:
            result = self._runner(
                [*self.command, "--message", message],
                ProcessOptions(
                    env=child_environment,
                    timeout_seconds=self.timeout_seconds,
                    capture_limit=_MAX_NOTIFICATION_OUTPUT_BYTES,
                ),
            )
        except ProcessTimeoutError:
            msg = "timeout"
            raise NotificationError(msg) from None
        except ProcessOutputLimitError:
            msg = "output_too_large"
            raise NotificationError(msg) from None
        except OSError as exc:
            msg = f"exec_{type(exc).__name__}"
            raise NotificationError(msg) from None
        if result.returncode != 0:
            msg = f"exit_{result.returncode}"
            raise NotificationError(msg)
        if self.require_private_receipt:
            self.validate_private_receipt(result.stdout)

    @staticmethod
    def validate_private_receipt(response_text: str) -> None:
        """Require a verified requester-private delivery receipt.

        Raises:
            NotificationError: If private notification delivery cannot be verified.

        """
        try:
            receipt_line = response_text.strip().splitlines()[-1]
        except IndexError:
            msg = "invalid_private_receipt"
            raise NotificationError(msg) from None
        try:
            receipt = decode_json(receipt_line)
        except ValueError:
            msg = "invalid_private_receipt"
            raise NotificationError(msg) from None
        valid_receipt = isinstance(receipt, dict) and all(
            (
                receipt.get("status") == "sent",
                receipt.get("policy") == "personal-first",
                receipt.get("route_kind") == "private",
                receipt.get("requester_key") == "seth-ori",
                receipt.get("destination_ref") == "seth-ori",
            ),
        )
        if not valid_receipt:
            msg = "invalid_private_receipt"
            raise NotificationError(msg)
