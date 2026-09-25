# Copyright (c) 2026 PitchAI. All rights reserved.
"""Error classification shared by sandbox runtime boundaries."""

from __future__ import annotations

from domain_checks.common_check import is_browser_infrastructure_error


class BrowserStartupError(RuntimeError):
    """Raised when the sandbox cannot start its Chromium session."""


EXPECTED_SUBMISSION_ERRORS: tuple[type[Exception], ...] = (
    ArithmeticError,
    AssertionError,
    AttributeError,
    BufferError,
    EOFError,
    ExceptionGroup,
    ImportError,
    LookupError,
    NameError,
    OSError,
    ReferenceError,
    RuntimeError,
    SyntaxError,
    TypeError,
    ValueError,
    Warning,
)


type TextValue = str | BaseException | None


def safe_text(value: TextValue, *, maximum_length: int) -> str:
    """Return bounded text suitable for runner result and artifact fields.

    Returns:
        Text truncated to the configured maximum length.
    """
    text = str(value or "")
    return text if len(text) <= maximum_length else text[:maximum_length]


def is_infrastructure_failure(error: BaseException) -> bool:
    """Classify whether a sandbox exception represents browser infrastructure.

    Returns:
        Whether the runner should report infrastructure degradation.
    """
    if isinstance(error, BrowserStartupError):
        return True
    return isinstance(error, Exception) and is_browser_infrastructure_error(error)
