# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed test-runner boundary for the E2E runner package tests."""

from __future__ import annotations

from importlib import import_module
from typing import Never, Protocol, cast


class PytestModule(Protocol):
    """Test-runner surface consumed by the runner heartbeat proof."""

    def fail(self, reason: str) -> Never:
        """Fail the active runner test with its measured reason."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


pytest = cast("PytestModule", cast("object", import_module("pytest")))
