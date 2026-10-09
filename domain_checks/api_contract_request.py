# Copyright (c) 2026 PitchAI. All rights reserved.
"""Original API check preparation order and explicit immutable request fields."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast
from urllib.parse import urljoin

from .api_contract_values import as_list
from .synthetic_values import substitute_env_refs

if TYPE_CHECKING:
    from .event_bus_delivery import JsonObject, JsonValue


@dataclass(frozen=True)
class ApiExpectation:
    """Validation inputs normalized before request body/header processing."""

    statuses: list[int]
    content_type: str | None
    required: list[str]
    equal: JsonObject
    max_elapsed_ms: float | None

    @classmethod
    def read(cls, raw: JsonObject) -> Self:
        """Return original conversions, preserving invalid status failures and optional limits."""
        status_values = as_list(raw.get("expected_status_codes") or raw.get("expected_status") or [200])
        statuses = [int(cast("str | int | float", value)) for value in status_values]
        content_type = "application/json"
        if "expected_content_type_contains" in raw:
            value = raw.get("expected_content_type_contains")
            content_type = None if value is None else str(value).strip() or None
        paths = as_list(raw.get("json_paths_required"))
        present_paths = [value for value in paths if str(value or "").strip()]
        required = [str(value) for value in present_paths]
        equal_value = raw.get("json_paths_equal")
        equal = equal_value if isinstance(equal_value, dict) else {}
        elapsed_value = raw.get("max_elapsed_ms")
        elapsed = None
        # Optional limits retained their original ordinary-error fallback.
        with suppress(Exception):
            elapsed = float(cast("str | int | float", elapsed_value)) if elapsed_value is not None else None
        return cls(statuses, content_type, required, equal, elapsed)


@dataclass(frozen=True)
class ApiBody:
    """The two independent body arguments accepted by the existing HTTPX call."""

    json: dict[str, JsonValue] | list[JsonValue] | None
    text: str | None

    @classmethod
    def read(cls, raw: JsonObject) -> Self:
        """Return existing JSON admission and text substitution before request timing."""
        json_value = raw.get("body_json")
        body_json = json_value if isinstance(json_value, (dict, list)) else None
        text_value = raw.get("body_text")
        body_text = substitute_env_refs(text_value) if isinstance(text_value, str) else None
        return cls(body_json, body_text)


@dataclass(frozen=True)
class ApiCheck:
    """Prepared identity, expectations and raw headers for exactly one request."""

    name: str
    method: str
    url: str
    expected: ApiExpectation
    body: ApiBody
    headers: JsonObject

    @classmethod
    def read(cls, raw: JsonObject, base: str) -> Self:
        """Return the original preparation order; unresolved URL/body placeholders propagate."""
        name = str(raw.get("name") or raw.get("path") or raw.get("url") or "api_check").strip()[:80]
        method = str(raw.get("method") or "GET").strip().upper()
        path = str(raw.get("path") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not url:
            if not path.startswith("/"):
                path = "/" + path if path else ""
            url = urljoin(base.rstrip("/") + "/", path)
        url = substitute_env_refs(url)
        expected = ApiExpectation.read(raw)
        body = ApiBody.read(raw)
        header_value = raw.get("headers")
        headers = header_value if isinstance(header_value, dict) else {}
        return cls(name, method, url, expected, body, headers)
