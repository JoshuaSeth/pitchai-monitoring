# Copyright (c) 2026 PitchAI. All rights reserved.
"""Expected-failure recorder for the exporter's IO and CLI edges."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from types import TracebackType


@final
class ExpectedFailure:
    """Swallow a block's expected exception types and keep the type name for reporting.

    This is ``contextlib.suppress`` for edges that must still say which failure
    happened (for example ``deliver_error`` or a per-cell lane error code).
    Unexpected exception types propagate unchanged.
    """

    expected: tuple[type[Exception], ...]
    name: str | None
    message: str | None

    def __init__(self, *expected: type[Exception]) -> None:
        """Expect any of the given exception types."""
        self.expected = expected
        self.name = None
        self.message = None

    def __enter__(self) -> ExpectedFailure:
        """Return this recorder so the caller can read ``name`` after the block."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        """Swallow an expected exception and remember its type name; let anything else propagate.

        Returns:
            Whether the exception was expected and is therefore swallowed.
        """
        if kind is None or not issubclass(kind, self.expected):
            return False
        self.name = kind.__name__
        self.message = str(value) if value is not None else ""
        return True
