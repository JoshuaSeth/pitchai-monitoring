# Copyright (c) 2026 PitchAI. All rights reserved.
"""Describe how banked reset credits affect runout calculations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import BankedResetPolicy


def banked_reset_policy(available_count: int) -> "BankedResetPolicy":
    """Declare that read-only forecasts never redeem banked resets.

    Returns:
        The resulting value.

    """
    return {
        "available_count": available_count,
        "included_as_automatic_capacity": False,
        "reason": ("Banked resets require an explicit redemption action; this dashboard is read-only."),
    }
