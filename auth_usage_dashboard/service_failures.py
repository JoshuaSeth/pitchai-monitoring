# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit failure capture for the dashboard's broker, history, and environment edges."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from types import TracebackType


@final
class FailureCapture[FailureT: BaseException]:
    """Stop one expected failure at an IO edge and keep it for the caller to report.

    Exceptions outside the expected types keep propagating unchanged, exactly as
    with an ``except`` clause naming the same types.
    """

    error: FailureT | None
    _expected: tuple[type[FailureT], ...]

    def __init__(self, *expected: type[FailureT]) -> None:
        """Expect only the given failure types."""
        self._expected = expected
        self.error = None

    def __enter__(self) -> Self:
        """Start capturing.

        Returns:
            This capture, whose ``error`` holds the expected failure once the block raised it.
        """
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Record and stop an expected failure.

        Returns:
            Whether the block raised an expected failure that is now recorded.
        """
        if isinstance(exception, self._expected):
            self.error = exception
            return True
        return False
