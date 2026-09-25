# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared error contract for declarative browser step validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepFlowValidationError(Exception):
    """Report one stable, user-facing definition validation failure."""

    message: str

    def __str__(self) -> str:
        """Return the stable validation message."""
        return self.message
