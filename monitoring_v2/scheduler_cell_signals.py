# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure health-signal construction for one scheduler cell observation."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .json_types import bool_value, text_value
from .scheduler_cell_directory import pressure_number

if TYPE_CHECKING:
    from .scheduler_cell_directory import SchedulerCellObservation

_HEARTBEAT_FRESHNESS_SECONDS = 45.0
_PROJECTION_FRESHNESS_SECONDS = 120.0
_DIRECT_ACCEPTANCE_LAG_SECONDS = 120.0
_DIRECT_OBSERVATION_GRACE_SECONDS = 60.0
_CRITICAL_FREE_BYTES = 10 * 1024**3
_CRITICAL_USED_PERCENT = 98.0
_MONITORING_CELL_SLUG = "dev-monitoring-cell"


class SchedulerCellSignal(NamedTuple):
    """One evaluated, healthy, or temporarily unobservable condition."""

    key: str
    failed: bool | None
    grace_seconds: float
    reason: str
    evidence: tuple[str, ...]


def scheduler_cell_signals(
    cell: SchedulerCellObservation,
    *,
    direct_feature_seen: bool,
    projection_feature_seen: bool,
    now: float,
) -> tuple[SchedulerCellSignal, ...]:
    """Return non-overlapping liveness, projection, direct, and storage signals."""
    liveness = _liveness_signal(cell, now=now)
    observable = liveness.failed is False
    return (
        liveness,
        _storage_signal(cell, observable=observable),
        *_projection_signals(cell, feature_seen=projection_feature_seen, observable=observable, now=now),
        *_direct_signals(cell, feature_seen=direct_feature_seen, observable=observable),
    )


def _liveness_signal(cell: SchedulerCellObservation, *, now: float) -> SchedulerCellSignal:
    reasons: list[str] = []
    if cell.registry_status != "active":
        reasons.append(f"registry status={cell.registry_status}")
    if cell.status != "online":
        reasons.append(f"cell status={cell.status}")
    if cell.health != "healthy":
        reasons.append(f"cell health={cell.health}")
    if not cell.placement_eligible:
        reasons.append("central placement eligibility=false")
    heartbeat_age = None if cell.last_received_at_ts is None else max(now - cell.last_received_at_ts, 0.0)
    if heartbeat_age is None:
        reasons.append("central has no cell heartbeat")
    elif heartbeat_age > _HEARTBEAT_FRESHNESS_SECONDS:
        reasons.append(f"heartbeat age={heartbeat_age:.1f}s exceeds {_HEARTBEAT_FRESHNESS_SECONDS:.0f}s")
    reasons.extend(_runtime_contract_reasons(cell))
    heartbeat = "none" if cell.last_received_at is None else cell.last_received_at
    evidence = (
        f"cell={cell.slug} boot={cell.boot_id or 'none'} central_last_received_at={heartbeat}",
        f"registry={cell.registry_status} status={cell.status} health={cell.health}",
        *(reasons or ("cell heartbeat and scheduler runtime contract are healthy",)),
    )
    return SchedulerCellSignal("cell_liveness", bool(reasons), 0.0, "; ".join(reasons), evidence)


def _runtime_contract_reasons(cell: SchedulerCellObservation) -> list[str]:
    pressure = cell.pressure
    reasons: list[str] = []
    if pressure_number(pressure, "app_server_ready") != 1:
        reasons.append("app server readiness=false")
    general_create_eligible = pressure_number(pressure, "general_agent_create_eligible")
    if cell.slug == _MONITORING_CELL_SLUG:
        if general_create_eligible != 0:
            reasons.append("monitoring new-lane isolation=false")
    elif general_create_eligible != 1:
        reasons.append("general new-lane runtime readiness=false")
    if pressure_number(pressure, "new_lane_storage_ready") != 1:
        reasons.append("selected new-lane storage readiness=false")
    services = [item for item in cell.services if text_value(item.get("workload_key")) == "agent_runtime"]
    if len(services) != 1:
        reasons.append(f"agent_runtime service count={len(services)}")
    elif bool_value(services[0].get("placement_eligible")) is not True:
        reasons.append("agent_runtime service eligibility=false")
    elif text_value(services[0].get("reported_health")) != "healthy":
        reasons.append(f"agent_runtime service health={text_value(services[0].get('reported_health')) or 'unknown'}")
    agent_routes = [item for item in cell.routes if text_value(item.get("workload_key")) == "agent_runtime"]
    cell_v2_routes = [
        item for item in agent_routes if text_value(item.get("compatibility_mode")) == "cell_v2"
    ]
    active_v2_routes = [item for item in cell_v2_routes if text_value(item.get("status")) == "active"]
    if len(active_v2_routes) != 1:
        reasons.append(f"active cell-v2 route count={len(active_v2_routes)}")
    return reasons


def _projection_signals(
    cell: SchedulerCellObservation,
    *,
    feature_seen: bool,
    observable: bool,
    now: float,
) -> tuple[SchedulerCellSignal, ...]:
    if not feature_seen or not observable:
        return ()
    age = None if cell.projection_received_at_ts is None else max(now - cell.projection_received_at_ts, 0.0)
    failed = age is None or age > _PROJECTION_FRESHNESS_SECONDS
    rendered_age = "none" if age is None else f"{age:.1f}s"
    reason = f"central projection receipt age={rendered_age} exceeds {_PROJECTION_FRESHNESS_SECONDS:.0f}s"
    evidence = (
        f"cell={cell.slug} boot={cell.boot_id or 'none'} projection_sequence={cell.projection_sequence}",
        f"projection_received_at={cell.projection_received_at or 'none'} age={rendered_age}",
        f"heartbeat_received_at={cell.last_received_at or 'none'} remains fresh",
    )
    return (SchedulerCellSignal("projection_visibility", failed, 0.0, reason, evidence),)


def _direct_signals(
    cell: SchedulerCellObservation,
    *,
    feature_seen: bool,
    observable: bool,
) -> tuple[SchedulerCellSignal, ...]:
    if not feature_seen or not observable:
        return ()
    declared_ready = pressure_number(cell.pressure, "direct_unaccepted_observation_ready") == 1
    count = pressure_number(cell.pressure, "direct_unaccepted_work_count")
    age = pressure_number(cell.pressure, "direct_unaccepted_oldest_age_seconds")
    requested = pressure_number(cell.pressure, "direct_unaccepted_requested_count")
    dispatching = pressure_number(cell.pressure, "direct_unaccepted_dispatching_count")
    complete = all(value is not None and value >= 0 for value in (count, age, requested, dispatching))
    ready = declared_ready and complete
    evidence = (
        (
            f"direct observation declared_ready={'yes' if declared_ready else 'no'} "
            f"validated_ready={'yes' if ready else 'no'} count={count if count is not None else 'unknown'}"
        ),
        f"oldest_age_seconds={age if age is not None else 'unknown'} requested={requested} dispatching={dispatching}",
    )
    unavailable = SchedulerCellSignal(
        "direct_delivery_observation",
        not ready,
        _DIRECT_OBSERVATION_GRACE_SECONDS,
        (
            "cell reported direct-delivery observation ready with missing or malformed samples"
            if declared_ready and not complete
            else "cell could not read its direct-delivery acceptance state for at least 60 seconds"
        ),
        evidence,
    )
    lagged = ready and count is not None and count > 0 and age is not None and age >= _DIRECT_ACCEPTANCE_LAG_SECONDS
    lag_reason = f"{int(count or 0)} direct handoff(s) remain unaccepted; oldest is {float(age or 0):.1f}s old"
    lag = SchedulerCellSignal("direct_delivery_lag", lagged if ready else None, 0.0, lag_reason, evidence)
    return unavailable, lag


def _storage_signal(cell: SchedulerCellObservation, *, observable: bool) -> SchedulerCellSignal:
    if not observable:
        return SchedulerCellSignal("storage_capacity", None, 0.0, "cell runtime is not observable", ())
    root_used = pressure_number(cell.pressure, "root_disk_used_percent")
    root_free = pressure_number(cell.pressure, "root_disk_free_bytes")
    work_used = pressure_number(cell.pressure, "work_storage_used_percent")
    work_free = pressure_number(cell.pressure, "work_storage_free_bytes")
    work_root = text_value(cell.pressure.get("new_lane_storage_root")) or "unknown"
    if root_used is None or root_free is None or work_used is None or work_free is None:
        return SchedulerCellSignal("storage_capacity", None, 0.0, "storage samples unavailable", ())
    root_critical = bool(root_used >= _CRITICAL_USED_PERCENT or root_free <= _CRITICAL_FREE_BYTES)
    work_critical = bool(work_used >= _CRITICAL_USED_PERCENT or work_free <= _CRITICAL_FREE_BYTES)
    master = pressure_number(cell.pressure, "master_service_host") == 1
    same_device = pressure_number(cell.pressure, "work_storage_same_device_as_root") == 1
    relationship = "same-device" if same_device else "separate-device"
    evidence = (
        (
            f"root=/ used={root_used:.1f}% free={root_free / 1024**3:.1f}GiB "
            f"master_service_host={'yes' if master else 'no'}"
        ),
        f"new_lane_storage={work_root} used={work_used:.1f}% free={work_free / 1024**3:.1f}GiB {relationship}",
    )
    critical_roots: list[str] = []
    if root_critical:
        critical_roots.append("root /")
    if work_critical:
        critical_roots.append(work_root)
    reason = f"critical storage capacity on {', '.join(critical_roots)}"
    if root_critical and not work_critical and not same_device:
        reason += f"; new work storage {work_root} remains healthy and must protect root"
    return SchedulerCellSignal("storage_capacity", root_critical or work_critical, 0.0, reason, evidence)
