# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared helpers for the token ledger and burn factor tests (no pytest dependency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .token_ledger.failures import ExpectedFailure

if TYPE_CHECKING:
    from collections.abc import Callable


def value_error_text[Result](action: Callable[[], Result]) -> str:
    """Return the message of the ValueError ``action`` raises, or an empty string."""
    with ExpectedFailure(ValueError) as failure:
        action()
    return failure.message or ""
