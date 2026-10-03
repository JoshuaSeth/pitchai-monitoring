# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing Chromium/driver failure classification shared by monitor and sandbox."""

from __future__ import annotations


def is_browser_infra_error(error: Exception) -> bool:
    """Classify the original browser-close, renderer and driver failure markers.

    Returns:
        True for the same infra errors previously classified in common_check.
    """
    name = type(error).__name__
    message = str(error or "").lower()
    if name == "TargetClosedError":
        return True
    return any(marker in message for marker in (
        "target page, context or browser has been closed", "browser has been closed", "page crashed",
        "target crashed", "connection closed while reading from the driver",
        "connection closed while writing to the driver", "pipe closed by peer",
    ))
