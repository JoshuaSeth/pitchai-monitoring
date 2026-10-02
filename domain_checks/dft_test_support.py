# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dependency-free assertions for the isolated DFT consumer contracts."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


def require(*, condition: bool, message: str) -> None:
    """Fail a test explicitly when its behavioral requirement is false.

    Raises:
        AssertionError: The tested requirement is not satisfied.
    """
    if not condition:
        raise AssertionError(message)


@contextmanager
def require_error(expected: type[Exception], code: str) -> Generator[None]:
    """Require a particular error without depending on external test packages.

    Yields:
        Control to the isolated operation under test.

    Raises:
        AssertionError: The operation returned or raised the wrong fixed code.
    """
    try:
        yield
    except expected as error:
        require(condition=code in str(error), message="error did not contain the required fixed code")
    else:
        message = "operation unexpectedly succeeded"
        raise AssertionError(message)
