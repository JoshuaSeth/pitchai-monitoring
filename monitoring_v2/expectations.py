# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed test expectations that remain active under optimized Python."""

from __future__ import annotations

from .testing_runtime import pytest


def present[T](value: T | None, *, label: str) -> T:
    """Return a required value or fail the current test.

    Returns:
        The narrowed non-null value.
    """
    if value is None:
        pytest.fail(label)
    return value
