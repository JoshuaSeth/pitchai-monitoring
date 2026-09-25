# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed contracts for API monitoring checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


class ApiContractCheckResult(NamedTuple):
    """Represent one API contract check outcome."""

    domain: str
    name: str
    ok: bool
    url: str
    status_code: int | None
    elapsed_ms: float | None
    error: str | None
    details: JsonObject


class ApiCheckSpec(NamedTuple):
    """Hold one normalized API check configuration."""

    name: str
    method: str
    url: str
    expected_statuses: list[int]
    expected_content_type: str | None
    json_required: list[str]
    json_equal: JsonObject
    max_elapsed_ms: float | None
    request_json: JsonObject | list[JsonValue] | None
    request_data: str | None
    headers: JsonObject
