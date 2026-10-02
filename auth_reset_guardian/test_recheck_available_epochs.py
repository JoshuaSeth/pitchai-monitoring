# Copyright (c) 2026 PitchAI. All rights reserved.
"""Unrelated available quota epochs cannot starve an expiry-priority reset."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from .models import ConsumeResult
from .test_organization_expiry import with_end
from .test_organization_support import (
    NOW,
    SequencedSource,
    account_observation,
    require_equal,
    reset_credit,
    run_guardian,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_other_epoch_change_only_ignored_for_available_capacity(tmp_path: Path) -> None:
    """Keep exhausted fleet epochs strict while allowing unrelated available jitter."""
    for other_used, expected_calls in ((10, 1), (100, 0)):
        source = _epoch_change_source(other_used)
        _ = run_guardian(tmp_path / f"audit-{other_used}.sqlite3", source=source, now=NOW)
        require_equal(len(source.consume_calls), expected_calls)


def _epoch_change_source(other_used: int) -> SequencedSource:
    """Build consecutive observations that differ only in an unrelated epoch.

    Returns:
        A simulated source for both available and exhausted peer scenarios.
    """
    credit = reset_credit("target", expires_at=NOW + timedelta(days=20))
    target = with_end(account_observation("target@example.test", credit_bank=(credit,)), "2026-09-08")
    post = with_end(account_observation("target@example.test", used_percent=0), "2026-09-08")
    other = account_observation("other@example.test", used_percent=other_used)
    changed = account_observation(
        "other@example.test", used_percent=other_used,
        weekly_reset_at=NOW + timedelta(days=7, seconds=1),
    )
    return SequencedSource(
        (target.descriptor, other.descriptor),
        {target.descriptor.account_ref: [target, target, post], other.descriptor.account_ref: [other, changed]},
        [ConsumeResult(code="reset", windows_reset=1)],
    )
