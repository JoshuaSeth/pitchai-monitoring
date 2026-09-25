# Copyright (c) 2026 PitchAI. All rights reserved.
"""Requester-private Telegram notification boundary for ASTRA matches."""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING, Protocol, cast, final

from .json_types import JsonObject, string_object_dict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .json_types import UntrustedValue


@final
class NotificationError(RuntimeError):
    """A sanitized private-delivery failure."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


class Notifier(Protocol):
    """Deliver only to the authorized private requester route."""

    def preflight(self) -> JsonObject:
        """Prove the route is private without sending a message."""
        raise NotImplementedError

    def notify(self, message: str) -> JsonObject:
        """Send one sensitive automation message and return a sanitized receipt."""
        raise NotImplementedError


@final
class PrivateCommandNotifier:
    """Invoke the reviewed Telegram helper without a shell."""

    def __init__(self, command: Sequence[str], *, timeout_seconds: float = 30.0):
        if not command:
            raise ValueError("notification command must not be empty")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def _run(self, extra_arguments: Sequence[str]) -> JsonObject:
        child_environment = {"HOME": "/root", "LANG": "C.UTF-8", "PATH": os.defpath}
        try:
            result = subprocess.run(
                [*self.command, *extra_arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                env=child_environment,
            )
        except subprocess.TimeoutExpired:
            raise NotificationError("timeout") from None
        except OSError as exc:
            raise NotificationError(f"exec_{type(exc).__name__}") from None
        if result.returncode != 0:
            raise NotificationError(f"exit_{result.returncode}")
        try:
            receipt = cast(
                "UntrustedValue",
                json.loads(result.stdout.strip().splitlines()[-1]),
            )
        except (IndexError, json.JSONDecodeError):
            raise NotificationError("invalid_private_receipt") from None
        typed_receipt = string_object_dict(receipt)
        if typed_receipt is None:
            raise NotificationError("invalid_private_receipt")
        return typed_receipt

    @staticmethod
    def _validate_private_receipt(
        receipt: JsonObject,
        expected_status: str,
    ) -> None:
        expected = {
            "status": expected_status,
            "policy": "personal-first",
            "route_kind": "private",
            "requester_key": "seth-ori",
            "destination_ref": "seth-ori",
        }
        if any(receipt.get(key) != value for key, value in expected.items()):
            raise NotificationError("invalid_private_receipt")

    def preflight(self) -> JsonObject:
        """Run the helper's read-only requester-private route preflight."""
        receipt = self._run(("--preflight-only",))
        self._validate_private_receipt(receipt, "ready")
        return {
            key: receipt[key]
            for key in ("status", "policy", "route_kind", "requester_key")
        }

    def notify(self, message: str) -> JsonObject:
        """Send one authorized sensitive message to the requester-private route."""
        receipt = self._run(("--message", message))
        self._validate_private_receipt(receipt, "sent")
        return {
            key: receipt[key]
            for key in ("status", "policy", "route_kind", "requester_key")
        }
