# Copyright (c) 2026 PitchAI. All rights reserved.
"""Retain expected input failures as explicit extraction outcomes.

Use this boundary only around a file read, external request or input decoder.
Callers inspect ``error`` and record missingness before using a result. Unexpected
exceptions propagate. The boundary never retries, logs private input or converts
failed reads into successful observations.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import TracebackType


@dataclass
class InputFailure(AbstractContextManager["InputFailure"]):
    """Capture a declared input failure for the caller's explicit status handling."""

    expected: type[Exception] | tuple[type[Exception], ...]
    error: BaseException | None = field(default=None, init=False)

    def __exit__(self, exception_type: type[BaseException] | None,
                 exception: BaseException | None, traceback: TracebackType | None) -> bool:
        """Retain a declared failure; propagate every unexpected exception.

        Returns:
            True only when the caller's declared input exception was captured.
        """
        if exception_type is None or traceback is None or not isinstance(exception, self.expected):
            return False
        self.error = exception
        return True
