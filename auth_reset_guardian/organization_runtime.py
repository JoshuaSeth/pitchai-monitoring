# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared mutable state for one organization guardian run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from .audit import AuditStore
    from .clients import GuardianSource
    from .guardian import Alert, GuardianRunSummary
    from .models import AccountDescriptor, AccountObservation
    from .organization_audit import OrganizationAttemptStore


@dataclass
class OrganizationRunContext:
    """Dependencies and accumulated evidence for one scheduled run."""

    source: GuardianSource
    audit: AuditStore
    claims: OrganizationAttemptStore
    clock: Callable[[], datetime]
    run_id: str
    summary: GuardianRunSummary
    alerts: list[Alert]


@dataclass(frozen=True)
class OrganizationInventory:
    """One complete broker inventory and its per-account provider observations."""

    descriptors: tuple[AccountDescriptor, ...]
    observations: dict[str, AccountObservation]
    failed_account_refs: set[str]
    inventory_failed: bool = False
