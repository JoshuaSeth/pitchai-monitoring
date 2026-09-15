# Copyright (c) 2026 PitchAI. All rights reserved.
"""Match diagnostic result severity to the inventory's alert policy."""

from __future__ import annotations

import logging


def domain_result_log_level(*, ok: bool, alertable: bool) -> int:
    """Keep quiet failures observable without emitting warning-level noise.

    Returns:
        Warning for an alertable failure, otherwise informational severity.
    """
    return logging.WARNING if not ok and alertable else logging.INFO
