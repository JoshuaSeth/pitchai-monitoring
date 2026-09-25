# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validate provider reset-credit consumption results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .model_values import PayloadError

if TYPE_CHECKING:
    from .json_contract import JsonValue


@dataclass(frozen=True)
class ConsumeResult:
    """Represent one normalized provider consume result."""

    code: str
    windows_reset: int

    @classmethod
    def from_provider(cls, payload: JsonValue) -> ConsumeResult:
        """Build a validated result from a provider payload.

        Returns:
            The validated consume result.

        Raises:
            PayloadError: If provider data violates the payload contract.

        """
        if not isinstance(payload, dict):
            msg = "provider consume response must be an object"
            raise PayloadError(msg)
        code = payload.get("code")
        if code not in {
            "reset",
            "nothing_to_reset",
            "no_credit",
            "already_redeemed",
        }:
            msg = "provider consume response contains an unsupported code"
            raise PayloadError(msg)
        raw_windows = payload.get("windows_reset", 0)
        if (
            isinstance(raw_windows, bool)
            or not isinstance(raw_windows, int)
            or raw_windows < 0
        ):
            msg = (
                "provider consume response windows_reset must be a non-negative integer"
            )
            raise PayloadError(msg)
        return cls(code=code, windows_reset=raw_windows)
