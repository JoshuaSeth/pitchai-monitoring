# Copyright (c) 2026 PitchAI. All rights reserved.
"""Normalize API monitoring configuration without exposing secrets."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, cast
from urllib.parse import urljoin

from .api_contract_coordination import InvalidCoordinationKeyError
from .api_contract_models import ApiContractSpec, ApiRequestSpec, ApiResponseExpectation

if TYPE_CHECKING:
    from .api_contract_models import ApiConfig, ApiValue

_ENV_REFERENCE = re.compile(r"\$\{([A-Z0-9_]{1,64})\}")


class MissingEnvironmentSecretsError(ValueError):
    """One or more referenced secret environment variables are absent."""

    def __init__(self, names: list[str]) -> None:
        """Initialize a secret-safe error containing variable names only."""
        message = f"missing_env_secrets: {sorted(set(names))}"
        super().__init__(message)


def _objects(value: ApiValue | None) -> list[ApiValue]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(cast("list[ApiValue]", value))
    return [value]


def _object_map(value: ApiValue | None) -> ApiConfig:
    if not isinstance(value, dict):
        return {}
    source = cast("dict[ApiValue, ApiValue]", value)
    return {str(key): item for key, item in source.items()}


def _substitute_environment(text: str) -> str:
    """Replace environment references while keeping values out of errors.

    Returns:
        Text with every declared environment reference replaced.

    Raises:
        MissingEnvironmentSecretsError: A referenced variable is absent.
    """
    missing: list[str] = []

    def replace_reference(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.getenv(name)
        if value is None:
            missing.append(name)
            return ""
        return value

    substituted = _ENV_REFERENCE.sub(replace_reference, text)
    if missing:
        raise MissingEnvironmentSecretsError(missing)
    return substituted


def _request_url(raw: ApiConfig, base_url: str) -> str:
    explicit = str(raw.get("url") or "").strip()
    if explicit:
        return _substitute_environment(explicit)
    path = str(raw.get("path") or "").strip()
    normalized_path = path if path.startswith("/") or not path else f"/{path}"
    return _substitute_environment(urljoin(f"{base_url.rstrip('/')}/", normalized_path))


def _request_spec(raw: ApiConfig, base_url: str) -> ApiRequestSpec:
    body = raw.get("body_json")
    json_body: ApiValue | None = cast("ApiValue", body) if isinstance(body, (dict, list)) else None
    text_value = raw.get("body_text")
    text_body = _substitute_environment(text_value) if isinstance(text_value, str) else None
    header_items = _object_map(raw.get("headers")).items()
    string_headers = ((key, str(value)) for key, value in header_items)
    resolved_headers = ((key, _substitute_environment(value)) for key, value in string_headers)
    headers = dict(resolved_headers)
    return ApiRequestSpec(
        method=str(raw.get("method") or "GET").strip().upper(),
        url=_request_url(raw, base_url),
        json_body=json_body,
        text_body=text_body,
        headers=headers,
    )


def _content_type(raw: ApiConfig) -> str | None:
    if "expected_content_type_contains" not in raw:
        return "application/json"
    value = raw.get("expected_content_type_contains")
    return None if value is None else str(value).strip() or None


def _response_expectation(raw: ApiConfig) -> ApiResponseExpectation:
    statuses_value = raw.get("expected_status_codes") or raw.get("expected_status") or [200]
    statuses = tuple(int(str(value)) for value in _objects(statuses_value))
    required_values = _objects(raw.get("json_paths_required"))
    required_text = (str(value or "").strip() for value in required_values)
    required_paths = tuple(text for text in required_text if text)
    elapsed_value = raw.get("max_elapsed_ms")
    max_elapsed_ms = None if elapsed_value is None else float(str(elapsed_value))
    return ApiResponseExpectation(
        statuses=statuses,
        content_type=_content_type(raw),
        required_paths=required_paths,
        equal_paths=_object_map(raw.get("json_paths_equal")),
        max_elapsed_ms=max_elapsed_ms,
    )


def build_api_contract_spec(raw: ApiConfig, base_url: str) -> ApiContractSpec:
    """Validate and normalize one API check.

    Returns:
        An immutable check specification ready for execution.

    Raises:
        InvalidCoordinationKeyError: The key is not text when present.
    """
    key_value = raw.get("coordination_key")
    if key_value is not None and not isinstance(key_value, str):
        raise InvalidCoordinationKeyError
    return ApiContractSpec(
        name=str(raw.get("name") or raw.get("path") or raw.get("url") or "api_check").strip()[:80],
        coordination_key=key_value,
        request=_request_spec(raw, base_url),
        expectation=_response_expectation(raw),
    )


def fallback_api_identity(raw: ApiConfig, base_url: str) -> tuple[str, str]:
    """Return a non-secret identity for a check that failed to normalize.

    Returns:
        The check name and an unsubstituted URL suitable for a failure result.
    """
    name = str(raw.get("name") or raw.get("path") or raw.get("url") or "api_check").strip()[:80]
    explicit = str(raw.get("url") or "").strip()
    path = str(raw.get("path") or "").strip()
    normalized_path = path if path.startswith("/") or not path else f"/{path}"
    return name, explicit or urljoin(f"{base_url.rstrip('/')}/", normalized_path)
