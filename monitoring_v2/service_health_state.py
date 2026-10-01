# Copyright (c) 2026 PitchAI. All rights reserved.
"""Evaluate retained progress evidence for one monitoring service role."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .json_types import json_object
from .service_health_evidence import age_seconds
from .service_health_model import (
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    STATUS_STARTING,
    STATUS_UNHEALTHY,
    HealthReport,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .json_types import JsonInput, JsonObject

STATE_MISSING: str = "state_missing"
STATE_TIMESTAMP_MISSING: str = "state_timestamp_missing"
AWAITING_FIRST_CYCLE: str = "awaiting_first_cycle"
PROGRESS_FRESH: str = "progress_fresh"


@dataclass(frozen=True)
class ProgressContext:
    """Times, thresholds and instance age shared by worker role probes.

    Attributes:
        now: Current epoch seconds.
        stale_seconds: Progress age that marks the worker as not progressing.
        grace_seconds: Startup window during which absent evidence may report
            ``starting`` instead of ``unhealthy``.
        extended_seconds: Role-specific long-activity window: the longest time a
            legitimate unit of work may hold the loop, or the age after which a
            supported central feed counts as stale.
        start_epoch: Container start epoch, ``None`` when procfs is unreadable.
    """

    now: float
    stale_seconds: int
    grace_seconds: int
    extended_seconds: int
    start_epoch: float | None


@dataclass(frozen=True)
class ProgressEvidence:
    """Role-specific progress parsed from one readable state document.

    Attributes:
        timestamp: Latest worker progress the state document proves.
        degraded_reason: Non-secret reason that forbids a ``healthy`` report.
        stale_reason: Reason code reported when this progress is too old.
        stale_seconds: Role-specific freshness override.
        detail: Additional non-secret evidence fields.
    """

    timestamp: float | None
    degraded_reason: str | None = None
    stale_reason: str = "progress_stale"
    stale_seconds: int | None = None
    detail: tuple[str, ...] = ()


type EvidenceExtractor = Callable[[JsonObject, ProgressContext], ProgressEvidence]


@dataclass(frozen=True)
class EvidenceSource:
    """One role's retained evidence document and how to read it.

    Attributes:
        role: Service role under evaluation.
        service: Deployed container or unit the role belongs to.
        path: State document that carries the progress evidence.
        extract: Role-specific extractor for the decoded document.
        missing_reason: Reason code used while the document is still absent.
    """

    role: str
    service: str
    path: Path
    extract: EvidenceExtractor
    missing_reason: str = STATE_MISSING


def read_evidence_payload(path: Path) -> JsonObject | None:
    """Read one JSON state document, returning ``None`` when it is absent.

    Read and decode failures are deliberately left to the caller's boundary
    classification instead of being flattened here.

    Returns:
        The decoded JSON object, or ``None`` when the document is absent.
    """
    if not path.exists():
        return None
    return json_object(cast("JsonInput", json.loads(path.read_text(encoding="utf-8"))))


def evaluate_progress(
    source: EvidenceSource,
    payload: JsonObject | None,
    context: ProgressContext,
) -> HealthReport:
    """Apply the shared worker-progress decision table for one service role.

    Args:
        source: Retained evidence document and its role-specific reader.
        payload: Decoded state document, ``None`` when it is still absent.
        context: Times, thresholds and instance age for this evaluation.

    Returns:
        A report separating missing, first-cycle, stale, degraded-dependency
        and healthy conditions for the probed role.
    """
    path_detail = (f"state_path={source.path}",)
    if payload is None:
        return startup_report(
            role=source.role,
            service=source.service,
            reason=source.missing_reason,
            detail=path_detail,
            context=context,
        )
    evidence = source.extract(payload, context)
    if evidence.timestamp is None:
        return HealthReport(
            role=source.role,
            service=source.service,
            status=STATUS_UNHEALTHY,
            reason=STATE_TIMESTAMP_MISSING,
            detail=(*path_detail, *evidence.detail),
        )
    if context.start_epoch is not None and evidence.timestamp < context.start_epoch:
        return startup_report(
            role=source.role,
            service=source.service,
            reason=AWAITING_FIRST_CYCLE,
            detail=(*path_detail, *evidence.detail),
            context=context,
        )
    stale_seconds = context.stale_seconds if evidence.stale_seconds is None else evidence.stale_seconds
    observed_age = age_seconds(context.now, evidence.timestamp)
    progress_detail = (f"state_age_seconds={round(observed_age)}", f"stale_after_seconds={stale_seconds}")
    if observed_age > float(stale_seconds):
        return HealthReport(
            role=source.role,
            service=source.service,
            status=STATUS_UNHEALTHY,
            reason=evidence.stale_reason,
            detail=(*progress_detail, *evidence.detail),
        )
    if evidence.degraded_reason is not None:
        return HealthReport(
            role=source.role,
            service=source.service,
            status=STATUS_DEGRADED,
            reason=evidence.degraded_reason,
            detail=(*progress_detail, *evidence.detail),
        )
    return HealthReport(
        role=source.role,
        service=source.service,
        status=STATUS_HEALTHY,
        reason=PROGRESS_FRESH,
        detail=(*progress_detail, *_instance_detail(context), *evidence.detail),
    )


def startup_report(
    *,
    role: str,
    service: str,
    reason: str,
    detail: tuple[str, ...],
    context: ProgressContext,
) -> HealthReport:
    """Return the bounded boot report for absent or not-yet-fresh evidence."""
    status = STATUS_STARTING if _inside_grace(context) else STATUS_UNHEALTHY
    return HealthReport(
        role=role,
        service=service,
        status=status,
        reason=reason,
        detail=(*detail, f"grace_seconds={context.grace_seconds}"),
    )


def _inside_grace(context: ProgressContext) -> bool:
    if context.start_epoch is None:
        return False
    return age_seconds(context.now, context.start_epoch) <= float(context.grace_seconds)


def _instance_detail(context: ProgressContext) -> tuple[str, ...]:
    if context.start_epoch is None:
        return ()
    return (f"instance_age_seconds={round(age_seconds(context.now, context.start_epoch))}",)
