# Copyright (c) 2026 PitchAI. All rights reserved.
"""Role registry and probe request for the monitoring service health contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .service_health_evidence import sanitize_fragment
from .service_health_progress import (
    database_dependency_progress,
    domain_incident_progress,
    monitor_progress,
    runner_heartbeat_progress,
    scheduler_observer_progress,
)
from .service_health_registry import registry_report
from .service_health_state import (
    EvidenceSource,
    ProgressContext,
    evaluate_progress,
    read_evidence_payload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .service_health_model import HealthReport
    from .service_health_request import HealthProbeRequest
    from .service_health_state import EvidenceExtractor

_REGISTRY_ROLE: Final = "registry"


class UsageError(ValueError):
    """A health probe invocation that does not name a supported role."""


@dataclass(frozen=True)
class ProgressBudget:
    """Freshness thresholds one worker role must satisfy.

    Attributes:
        stale_seconds: Progress age that means the worker stopped progressing.
        grace_seconds: Startup window during which absent evidence reports
            ``starting`` instead of ``unhealthy``.
        extended_seconds: Role-specific long-activity window: the longest time a
            legitimate unit of work may hold the loop, or the age after which a
            supported central feed counts as stale.
    """

    stale_seconds: int
    grace_seconds: int
    extended_seconds: int


@dataclass(frozen=True)
class RoleSpec:
    """One deployed monitoring service and the evidence it must keep fresh.

    Attributes:
        role: Role name accepted by ``--role``.
        service: Deployed container the role runs in.
        evidence_env: Environment variable overriding the evidence path.
        evidence_default: Evidence path used when the variable is unset.
        missing_reason: Reason code used while the evidence is still absent.
        budget: Freshness thresholds for this role.
        extract: Progress extractor, absent for the HTTP-only registry role.
    """

    role: str
    service: str
    evidence_env: str
    evidence_default: str
    missing_reason: str
    budget: ProgressBudget
    extract: EvidenceExtractor | None = None


_ROLE_SPECS: Final[Mapping[str, RoleSpec]] = {
    "monitor": RoleSpec(
        role="monitor",
        service="service-monitoring",
        evidence_env="STATE_PATH",
        evidence_default="/data/state.json",
        missing_reason="state_missing",
        budget=ProgressBudget(stale_seconds=600, grace_seconds=300, extended_seconds=0),
        extract=monitor_progress,
    ),
    "registry": RoleSpec(
        role=_REGISTRY_ROLE,
        service="e2e-registry",
        evidence_env="E2E_REGISTRY_DB_PATH",
        evidence_default="/data/e2e-registry.db",
        missing_reason="registry_database_missing",
        budget=ProgressBudget(stale_seconds=0, grace_seconds=120, extended_seconds=0),
    ),
    "runner": RoleSpec(
        role="runner",
        service="e2e-runner",
        evidence_env="E2E_RUNNER_HEARTBEAT_PATH",
        evidence_default="/run/pitchai-health/e2e-runner-heartbeat.json",
        missing_reason="runner_heartbeat_missing",
        budget=ProgressBudget(stale_seconds=120, grace_seconds=120, extended_seconds=14400),
        extract=runner_heartbeat_progress,
    ),
    "database-dependency": RoleSpec(
        role="database-dependency",
        service="database-dependency-monitor",
        evidence_env="DATABASE_DEPENDENCY_STATE_PATH",
        evidence_default="/data/database-dependencies.json",
        missing_reason="collector_state_missing",
        budget=ProgressBudget(stale_seconds=900, grace_seconds=600, extended_seconds=0),
        extract=database_dependency_progress,
    ),
    "scheduler-observer": RoleSpec(
        role="scheduler-observer",
        service="scheduler-placement-observer",
        evidence_env="SCHEDULER_INCIDENT_STATE_PATH",
        evidence_default="/data/scheduler-placement-observer.json",
        missing_reason="observer_state_missing",
        budget=ProgressBudget(stale_seconds=120, grace_seconds=300, extended_seconds=300),
        extract=scheduler_observer_progress,
    ),
    "domain-incident": RoleSpec(
        role="domain-incident",
        service="domain-incident-events",
        evidence_env="DOMAIN_INCIDENT_EVENT_STATE_PATH",
        evidence_default="/data/domain-incident-events.json",
        missing_reason="producer_state_missing",
        budget=ProgressBudget(stale_seconds=120, grace_seconds=300, extended_seconds=0),
        extract=domain_incident_progress,
    ),
}

SUPPORTED_ROLES: Final[tuple[str, ...]] = tuple(sorted(_ROLE_SPECS))


def role_spec(role: str) -> RoleSpec:
    """Return the deployment specification for one role.

    Args:
        role: Role name supplied on the command line.

    Returns:
        The deployment specification registered for ``role``.

    Raises:
        UsageError: If the role is not part of the deployed contract.
    """
    spec = _ROLE_SPECS.get(role)
    if spec is None:
        message = f"unsupported role {sanitize_fragment(role)}; expected one of {', '.join(SUPPORTED_ROLES)}"
        raise UsageError(message)
    return spec


def probe(request: HealthProbeRequest, *, now: float, start_epoch: float | None) -> HealthReport:
    """Return the evaluated health report for one resolved request.

    Args:
        request: Resolved role, evidence path and thresholds.
        now: Current epoch seconds.
        start_epoch: Container start epoch, ``None`` when procfs is unreadable.

    Returns:
        The evaluated health report for this role.
    """
    context = ProgressContext(
        now=now,
        stale_seconds=request.budget.stale_seconds,
        grace_seconds=request.budget.grace_seconds,
        extended_seconds=request.budget.extended_seconds,
        start_epoch=start_epoch,
    )
    spec = role_spec(request.role)
    if spec.extract is None:
        # The registry keeps no worker progress document: its contract is HTTP
        # liveness plus a read-only usability probe of the registry database.
        return registry_report(request=request, context=context)
    payload = read_evidence_payload(request.evidence_path)
    return evaluate_progress(
        EvidenceSource(
            role=request.role,
            service=request.service,
            path=request.evidence_path,
            extract=spec.extract,
            missing_reason=request.missing_reason,
        ),
        payload=payload,
        context=context,
    )
