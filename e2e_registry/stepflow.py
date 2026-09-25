# Copyright (c) 2026 PitchAI. All rights reserved.
"""Parsing and top-level validation for declarative browser step flows."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import yaml

from e2e_registry.stepflow_steps import normalize_steps
from e2e_registry.stepflow_types import StepFlowValidationError

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject, UntrustedJsonValue

_MAXIMUM_STEPS = 60
_MAXIMUM_NAME_LENGTH = 120

__all__ = [
    "StepFlowValidationError",
    "parse_definition_bytes",
    "validate_base_url",
    "validate_definition",
]


def _ensure_http_url(url: str) -> None:
    normalized = str(url or "").strip()
    if not normalized:
        message = "missing_base_url"
        raise StepFlowValidationError(message)
    parts = urlsplit(normalized)
    if (parts.scheme or "").lower() not in {"http", "https"}:
        message = "invalid_base_url_scheme"
        raise StepFlowValidationError(message)
    if not parts.netloc:
        message = "invalid_base_url_host"
        raise StepFlowValidationError(message)


def parse_definition_bytes(raw: bytes, *, content_type: str | None = None) -> JsonObject:
    """Decode one YAML or JSON definition into a mapping.

    Returns:
        The decoded definition mapping.

    Raises:
        StepFlowValidationError: If decoding fails or the document is not a mapping.
    """
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        message = "empty_definition"
        raise StepFlowValidationError(message)

    if content_type and "json" in content_type.lower():
        try:
            decoded = cast("UntrustedJsonValue", json.loads(text))
        except json.JSONDecodeError as exc:
            message = f"invalid_json: {exc}"
            raise StepFlowValidationError(message) from exc
    else:
        try:
            decoded = cast("UntrustedJsonValue", yaml.safe_load(text))
        except yaml.YAMLError as exc:
            message = f"invalid_yaml: {exc}"
            raise StepFlowValidationError(message) from exc

    if not isinstance(decoded, dict):
        message = "definition_must_be_object"
        raise StepFlowValidationError(message)
    return cast("JsonObject", decoded)


def validate_definition(definition: JsonObject) -> JsonObject:
    """Validate and normalize a declarative browser test definition.

    Returns:
        A bounded definition containing a name and normalized steps.

    Raises:
        StepFlowValidationError: If any definition or step field is invalid.
    """
    name_value = definition.get("name") or definition.get("test_name") or "test"
    name = str(name_value).strip()[:_MAXIMUM_NAME_LENGTH]
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        message = "missing_steps"
        raise StepFlowValidationError(message)
    if len(steps) > _MAXIMUM_STEPS:
        message = "too_many_steps"
        raise StepFlowValidationError(message)
    normalized_steps = normalize_steps(steps)
    return cast("JsonObject", {"name": name, "steps": normalized_steps})


def validate_base_url(base_url: str) -> str:
    """Return a stripped HTTP(S) base URL or reject it.

    Returns:
        The validated URL.
    """
    _ensure_http_url(base_url)
    return base_url.strip()
