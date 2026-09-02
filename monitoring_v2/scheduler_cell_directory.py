# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict central cell-directory reader for independent scheduler supervision."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

from .json_types import bool_value, object_list, optional_object, text_value
from .scheduler_incident_gateway import read_scheduler_json

if TYPE_CHECKING:
    from .json_types import JsonObject, JsonValue
    from .scheduler_incident_feed import SchedulerIncidentFeedConfig

_MAX_CELLS = 64
_MAX_SERVICES = 16
_MAX_ROUTES = 32


class SchedulerCellObservation(NamedTuple):
    """One validated, transport-secret-free cell health projection."""

    cell_id: str
    slug: str
    boot_id: str | None
    registry_status: str
    status: str
    health: str
    placement_eligible: bool
    last_received_at: str | None
    last_received_at_ts: float | None
    projection_sequence: int | None
    projection_received_at: str | None
    projection_received_at_ts: float | None
    services: tuple[JsonObject, ...]
    routes: tuple[JsonObject, ...]
    pressure: JsonObject


def read_scheduler_cell_directory(
    config: SchedulerIncidentFeedConfig,
) -> tuple[SchedulerCellObservation, ...]:
    """Read and validate the caller-scoped central cell directory.

    Returns:
        A bounded immutable cell snapshot.
    """
    payload = read_scheduler_json(
        url=config.directory_url,
        token=config.token,
        timeout_seconds=config.timeout_seconds,
        query={},
    )
    return scheduler_cell_directory(payload)


def scheduler_cell_directory(payload: JsonObject) -> tuple[SchedulerCellObservation, ...]:
    """Return a bounded, uniquely keyed cell snapshot from a directory payload.

    Raises:
        TypeError: If required arrays or cell fields are malformed.
        ValueError: If cell identifiers collide or timestamps are invalid.
    """
    raw_cells = payload.get("cells")
    cells = object_list(raw_cells)
    if not isinstance(raw_cells, list) or len(cells) != len(raw_cells) or len(cells) > _MAX_CELLS:
        message = "scheduler directory cells must be a bounded object array"
        raise TypeError(message)
    observations = tuple(_cell_observation(cell) for cell in cells)
    slugs = [cell.slug for cell in observations]
    identifiers = [cell.cell_id for cell in observations]
    if len(slugs) != len(set(slugs)) or len(identifiers) != len(set(identifiers)):
        message = "scheduler directory returned duplicate cell identities"
        raise ValueError(message)
    return observations


def pressure_number(pressure: JsonObject, key: str) -> float | None:
    """Return one finite JSON number while rejecting booleans."""
    value = pressure.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    selected = float(value)
    return selected if isfinite(selected) else None


def _cell_observation(cell: JsonObject) -> SchedulerCellObservation:
    raw_services = cell.get("services")
    raw_routes = cell.get("routes")
    services = object_list(raw_services)
    routes = object_list(raw_routes)
    if not isinstance(raw_services, list) or len(services) != len(raw_services) or len(services) > _MAX_SERVICES:
        message = "scheduler directory cell services must be a bounded object array"
        raise TypeError(message)
    if not isinstance(raw_routes, list) or len(routes) != len(raw_routes) or len(routes) > _MAX_ROUTES:
        message = "scheduler directory cell routes must be a bounded object array"
        raise TypeError(message)
    last_received_at, last_received_at_ts = _optional_timestamp(cell.get("last_received_at"))
    projection_received_at, projection_received_at_ts = _optional_timestamp(
        cell.get("projection_received_at"),
        field="projection_received_at",
    )
    boot_id = _optional_uuid(cell.get("boot_id"), field="boot_id")
    placement_eligible = bool_value(cell.get("placement_eligible"))
    if placement_eligible is None:
        message = "scheduler directory cell placement eligibility must be boolean"
        raise TypeError(message)
    return SchedulerCellObservation(
        cell_id=_required_uuid(cell.get("cell_id"), field="cell_id"),
        slug=_required_text(cell.get("slug"), field="slug", limit=63),
        boot_id=boot_id,
        registry_status=_required_text(cell.get("registry_status"), field="registry_status", limit=32),
        status=_required_text(cell.get("status"), field="status", limit=32),
        health=_required_text(cell.get("health"), field="health", limit=32),
        placement_eligible=placement_eligible,
        last_received_at=last_received_at,
        last_received_at_ts=last_received_at_ts,
        projection_sequence=_optional_nonnegative_integer(cell.get("projection_sequence")),
        projection_received_at=projection_received_at,
        projection_received_at_ts=projection_received_at_ts,
        services=tuple(services),
        routes=tuple(routes),
        pressure=optional_object(cell.get("pressure")),
    )


def _required_text(value: JsonValue | object, *, field: str, limit: int) -> str:
    selected = text_value(value).strip()
    if not selected or len(selected) > limit:
        message = f"scheduler directory field {field} is invalid"
        raise TypeError(message)
    return selected


def _required_uuid(value: JsonValue | object, *, field: str) -> str:
    selected = _required_text(value, field=field, limit=36)
    parsed = UUID(selected)
    if str(parsed) != selected:
        message = f"scheduler directory field {field} is not a canonical UUID"
        raise ValueError(message)
    return selected


def _optional_uuid(value: JsonValue | object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_uuid(value, field=field)


def _optional_nonnegative_integer(value: JsonValue | object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        message = "scheduler directory projection_sequence must be a non-negative integer"
        raise TypeError(message)
    return value


def _optional_timestamp(
    value: JsonValue | object,
    *,
    field: str = "last_received_at",
) -> tuple[str | None, float | None]:
    if value is None:
        return None, None
    selected = _required_text(value, field=field, limit=64)
    normalized = selected[:-1] + "+00:00" if selected.endswith("Z") else selected
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        message = f"scheduler directory {field} must include a timezone"
        raise ValueError(message)
    utc_value = parsed.astimezone(UTC)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z"), utc_value.timestamp()
