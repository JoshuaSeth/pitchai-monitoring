# Copyright (c) 2026 PitchAI. All rights reserved.
"""Response assertions for API contract checks."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import httpx

    from domain_checks.api_contract_models import ApiCheckSpec
    from domain_checks.types import JsonObject, JsonValue


def _get_path(value: JsonValue, path: str) -> tuple[bool, JsonValue]:
    current = value
    for segment in (path or "").split("."):
        cleaned_segment = segment.strip()
        if not cleaned_segment:
            return False, None
        if isinstance(current, list):
            try:
                index = int(cleaned_segment)
            except ValueError:
                return False, None
            if not 0 <= index < len(current):
                return False, None
            current = current[index]
            continue
        if isinstance(current, dict):
            if cleaned_segment not in current:
                return False, None
            current = current[cleaned_segment]
            continue
        return False, None
    return True, current


def _initial_error(spec: ApiCheckSpec, response: httpx.Response) -> str | None:
    if response.status_code not in spec.expected_statuses:
        return f"unexpected_status: {response.status_code} not in {spec.expected_statuses}"
    if spec.expected_content_type:
        content_type = (response.headers.get("content-type") or "").lower()
        if spec.expected_content_type.lower() not in content_type:
            return f"unexpected_content_type: {content_type!r} missing {spec.expected_content_type!r}"
    return None


def _missing_paths(data: JsonValue, paths: list[str]) -> list[JsonValue]:
    missing: list[JsonValue] = []
    for path in paths[:50]:
        exists, _value = _get_path(data, path)
        if not exists:
            missing.append(path)
    return missing


def _json_mismatches(data: JsonValue, expected: JsonObject) -> list[JsonValue]:
    mismatches: list[JsonValue] = []
    for path, expected_value in list(expected.items())[:50]:
        exists, actual_value = _get_path(data, str(path))
        if not exists:
            mismatches.append(f"{path}: missing")
        elif actual_value != expected_value:
            mismatches.append(
                f"{path}: got={actual_value!r} expected={expected_value!r}",
            )
    return mismatches


def _json_error(
    spec: ApiCheckSpec,
    response: httpx.Response,
    details: JsonObject,
) -> str | None:
    if not spec.json_required and not spec.json_equal:
        return None
    try:
        data = cast("JsonValue", response.json())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return f"json_parse_error: {type(exc).__name__}: {exc}"
    missing = _missing_paths(data, spec.json_required)
    if missing:
        details["missing_json_paths"] = missing[:25]
        return "missing_json_paths"
    mismatches = _json_mismatches(data, spec.json_equal)
    if mismatches:
        details["json_mismatches"] = mismatches[:25]
        return "json_value_mismatch"
    return None


def evaluate_api_response(
    spec: ApiCheckSpec,
    response: httpx.Response,
    elapsed_ms: float,
) -> tuple[str | None, JsonObject]:
    """Evaluate a response in the historical contract-check order.

    Returns:
        The first contract error, if any, and response diagnostics.
    """
    details: JsonObject = {
        "content_type": response.headers.get("content-type"),
        "final_url": str(response.url),
    }
    error = _initial_error(spec, response)
    if error is None:
        error = _json_error(spec, response, details)
    if error is None and spec.max_elapsed_ms is not None and elapsed_ms > spec.max_elapsed_ms:
        error = f"slow_api: elapsed_ms={elapsed_ms:.1f} > {spec.max_elapsed_ms:.1f}"
    return error, details
