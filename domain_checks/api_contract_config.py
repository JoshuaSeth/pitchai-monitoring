# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict parsing for API contract check configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from domain_checks.api_contract_models import ApiCheckSpec
from domain_checks.common_env import substitute_env_refs

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue


def _as_list(value: JsonValue) -> list[JsonValue]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _check_url(raw: JsonObject, base_url: str) -> str:
    path = str(raw.get("path") or "").strip()
    url = str(raw.get("url") or "").strip()
    if not url:
        if not path.startswith("/"):
            path = "/" + path if path else ""
        url = urljoin(base_url.rstrip("/") + "/", path)
    return substitute_env_refs(url)


def _expected_statuses(raw: JsonObject) -> list[int]:
    value = raw.get("expected_status_codes") or raw.get("expected_status")
    values = [200] if value is None else _as_list(value)
    statuses: list[int] = []
    for status in values:
        if not isinstance(status, bool | int | float | str):
            message = f"Invalid expected API status: {status!r}"
            raise TypeError(message)
        statuses.append(int(status))
    return statuses


def _expected_content_type(raw: JsonObject) -> str | None:
    if "expected_content_type_contains" not in raw:
        return "application/json"
    value = raw.get("expected_content_type_contains")
    return None if value is None else str(value).strip() or None


def _required_json_paths(raw: JsonObject) -> list[str]:
    paths: list[str] = []
    for value in _as_list(raw.get("json_paths_required")):
        path = str(value)
        if str(value or "").strip():
            paths.append(path)
    return paths


def _max_elapsed_ms(raw: JsonObject) -> float | None:
    value = raw.get("max_elapsed_ms")
    if value is None:
        return None
    if not isinstance(value, bool | int | float | str):
        message = f"Invalid max_elapsed_ms: {value!r}"
        raise TypeError(message)
    return float(value)


def _request_body(
    raw: JsonObject,
) -> tuple[JsonObject | list[JsonValue] | None, str | None]:
    body_json = raw.get("body_json")
    request_json = body_json if isinstance(body_json, dict | list) else None
    body_text = raw.get("body_text")
    request_data = body_text if isinstance(body_text, str) else None
    if request_data is not None:
        request_data = substitute_env_refs(request_data)
    return request_json, request_data


def parse_api_check(raw: JsonObject, base_url: str) -> ApiCheckSpec:
    """Validate and normalize one API contract check.

    Returns:
        The normalized API check specification.
    """
    request_json, request_data = _request_body(raw)
    equal_value = raw.get("json_paths_equal")
    headers_value = raw.get("headers")
    return ApiCheckSpec(
        name=str(
            raw.get("name") or raw.get("path") or raw.get("url") or "api_check",
        ).strip()[:80],
        method=str(raw.get("method") or "GET").strip().upper(),
        url=_check_url(raw, base_url),
        expected_statuses=_expected_statuses(raw),
        expected_content_type=_expected_content_type(raw),
        json_required=_required_json_paths(raw),
        json_equal=equal_value if isinstance(equal_value, dict) else {},
        max_elapsed_ms=_max_elapsed_ms(raw),
        request_json=request_json,
        request_data=request_data,
        headers=headers_value if isinstance(headers_value, dict) else {},
    )
