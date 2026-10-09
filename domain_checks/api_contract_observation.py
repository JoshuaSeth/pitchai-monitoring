# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP and response failure boundaries for sequential API contract checks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, cast

from .api_contract_values import headers_with_env, missing_paths, unequal_paths

if TYPE_CHECKING:
    from types import TracebackType

    from httpx import AsyncClient, Response

    from .api_contract_request import ApiCheck, ApiExpectation
    from .event_bus_delivery import JsonObject, JsonValue


@dataclass
class ApiObservation:
    """Original mutable observation fields, with timing starting after preparation."""

    started: float
    status_code: int | None = None
    elapsed_ms: float | None = None
    error: str | None = None
    details: JsonObject = field(default_factory=dict)
    ok: bool = True

    async def run(self, client: AsyncClient, check: ApiCheck, timeout_seconds: float) -> None:
        """Attempt a request and retain ordinary failures without consuming cancellation."""
        with ApiErrorScope(self):
            response = await client.request(
                check.method, check.url, json=check.body.json,
                content=check.body.text.encode("utf-8") if isinstance(check.body.text, str) else None,
                headers=headers_with_env(check.headers), timeout=float(timeout_seconds), follow_redirects=True,
            )
            self.status_code = int(response.status_code)
            self.elapsed_ms = (time.perf_counter() - self.started) * 1000.0
            self.details["content_type"] = response.headers.get("content-type")
            self.details["final_url"] = str(response.url)
            self.validate(response, check.expected)

    def validate(self, response: Response, expected: ApiExpectation) -> None:
        """Preserve status, content type, JSON presence/equality and elapsed-limit precedence."""
        if self.status_code not in expected.statuses:
            self.ok = False
            self.error = f"unexpected_status: {self.status_code} not in {expected.statuses}"
        if self.ok and expected.content_type:
            content_type = (response.headers.get("content-type") or "").lower()
            if expected.content_type.lower() not in content_type:
                self.ok = False
                self.error = f"unexpected_content_type: {content_type!r} missing {expected.content_type!r}"
        data: JsonValue = None
        if self.ok and (expected.required or expected.equal):
            with ApiErrorScope(self, "json_parse_error: "):
                data = cast("JsonValue", response.json())
        if self.ok and expected.required:
            missing = missing_paths(data, expected.required)
            if missing:
                self.ok = False
                self.error = "missing_json_paths"
                self.details["missing_json_paths"] = list(missing[:25])
        if self.ok and expected.equal:
            mismatches = unequal_paths(data, expected.equal)
            if mismatches:
                self.ok = False
                self.error = "json_value_mismatch"
                self.details["json_mismatches"] = list(mismatches[:25])
        if (self.ok and expected.max_elapsed_ms is not None and self.elapsed_ms is not None
                and float(self.elapsed_ms) > expected.max_elapsed_ms):
            self.ok = False
            self.error = f"slow_api: elapsed_ms={self.elapsed_ms:.1f} > {expected.max_elapsed_ms:.1f}"


@dataclass(frozen=True)
class ApiErrorScope:
    """Record the two existing Exception catch scopes while letting BaseException propagate."""

    observed: ApiObservation
    prefix: str = ""

    def __enter__(self) -> Self:
        """Return this error boundary without changing observation state."""
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _trace: TracebackType | None) -> bool:
        """Return true only after an ordinary failure is recorded with original timing."""
        if not isinstance(error, Exception):
            return False
        if not self.prefix:
            self.observed.elapsed_ms = (time.perf_counter() - self.observed.started) * 1000.0
        self.observed.ok = False
        self.observed.error = f"{self.prefix}{type(error).__name__}: {error}"
        return True
