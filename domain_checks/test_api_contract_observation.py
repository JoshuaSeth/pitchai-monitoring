# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated API check preparation, request, precedence and cancellation contracts."""

from __future__ import annotations

import asyncio
import os
import unittest
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .api_contract_values import get_path
from .dft_test_support import require
from .metrics_api_contract import run_api_contract_checks
from .synthetic_values import substitute_env_refs

if TYPE_CHECKING:
    from httpx import AsyncClient, Response

    from .event_bus_delivery import JsonValue


def response_fixture(status: int, content_type: str, data: JsonValue) -> Response:
    """Return a response double; native HTTPX decoding is covered by the retained differential proof."""
    headers = {"content-type": content_type}
    response = MagicMock(status_code=status, headers=headers, url="https://target.invalid/final",
                         json=MagicMock(return_value=data))
    return cast("Response", response)


class ApiContractObservationTests(unittest.IsolatedAsyncioTestCase):
    """No real client transport: every response and request await is substituted."""

    @staticmethod
    async def test_sequential_requests_preserve_root_path_body_headers_and_timing() -> None:
        """Configuration is normalized before each request, with the existing UTF-8 body."""
        response = response_fixture(200, "application/json", {"items": [{"id": 7}]})
        request = AsyncMock(return_value=response)
        client = cast("AsyncClient", MagicMock(request=request))
        inputs: list[JsonValue] = [None, {"name": " padded ", "path": "health", "method": " post ",
            "headers": {"X-Fixture": "${API_FIXTURE}"}, "body_text": "é${API_FIXTURE}",
            "body_json": {"sent": True}, "json_paths_required": ["items.0.id"]}, {}]
        with (patch.dict(os.environ, {"API_FIXTURE": "synthetic"}),
              patch("time.perf_counter", side_effect=[1.0, 1.25, 2.0, 2.5])):
            results = await run_api_contract_checks(http_client=client, domain=" TARGET.INVALID ",
                base_url=" https://target.invalid/page ", checks=inputs)
        first, second = results
        require(condition=(first.domain, first.name, first.url, first.elapsed_ms, second.elapsed_ms)
                == ("target.invalid", "padded", "https://target.invalid/health", 250.0, 500.0),
                message="normalization or observation clock changed")
        require(condition=first.ok and second.ok, message="healthy mocked requests failed")
        request.assert_any_await("POST", "https://target.invalid/health", json={"sent": True},
            content="ésynthetic".encode(), headers={"X-Fixture": "synthetic"}, timeout=10.0, follow_redirects=True)

    @staticmethod
    async def test_failure_precedence_and_retained_json_detail_limits() -> None:
        """HTTP/content-type failures win over JSON, required paths win over equality and time."""
        responses = [response_fixture(503, "text/plain; charset=utf-8", None),
                     response_fixture(200, "text/plain; charset=utf-8", None)]
        responses.extend(response_fixture(200, "application/json", {}) for _ in range(3))
        client = cast("AsyncClient", MagicMock(request=AsyncMock(side_effect=responses)))
        common: dict[str, JsonValue] = {"json_paths_required": ["needed"],
                                      "json_paths_equal": {"same": 1}, "max_elapsed_ms": -1}
        many: list[JsonValue] = []
        equal: dict[str, JsonValue] = {}
        for index in range(60):
            key = f"key{index}"
            many.append(key)
            equal[key] = 1
        checks: list[JsonValue] = [common, common, common,
            {"json_paths_required": many}, {"json_paths_equal": equal}]
        with patch("time.perf_counter", return_value=1.0):
            results = await run_api_contract_checks(http_client=client, domain="fixture", base_url="u", checks=checks)
        require(condition=[result.error for result in results] == ["unexpected_status: 503 not in [200]",
            "unexpected_content_type: 'text/plain; charset=utf-8' missing 'application/json'",
            "missing_json_paths", "missing_json_paths", "json_value_mismatch"], message="failure precedence changed")
        require(condition=results[3].details["missing_json_paths"] == many[:25], message="missing-path limit changed")
        require(condition=results[4].details["json_mismatches"] == [f"key{index}: missing" for index in range(25)],
                message="mismatch detail limit changed")

    @staticmethod
    async def test_json_parse_and_request_errors_keep_different_clock_boundaries() -> None:
        """JSON parsing retains request elapsed time; ordinary request errors sample failure time."""
        response = response_fixture(200, "application/json", None)
        response.json = MagicMock(side_effect=ValueError("json fixture"))
        request = AsyncMock(side_effect=[response, ValueError("request fixture")])
        client = cast("AsyncClient", MagicMock(request=request))
        with patch("time.perf_counter", side_effect=[1.0, 1.25, 2.0, 2.5]) as clock:
            results = await run_api_contract_checks(http_client=client, domain="fixture", base_url="u",
                                                   checks=[{"json_paths_required": ["a"]}, {}])
        expected_calls = 4
        require(condition=clock.call_count == expected_calls, message="JSON failure added a clock sample")
        require(condition=results[0].error is not None and results[0].error.startswith("json_parse_error: "),
                message="JSON error lost its classification")
        require(condition=(results[0].elapsed_ms, results[1].elapsed_ms, results[1].error)
                == (250.0, 500.0, "ValueError: request fixture"), message="error elapsed time changed")

    @staticmethod
    async def test_missing_placeholders_preserve_preparation_and_observation_boundaries() -> None:
        """Missing URL/body references propagate; header references become ordinary failed observations."""
        request = AsyncMock()
        client = cast("AsyncClient", MagicMock(request=request))
        with patch.dict(os.environ, {}, clear=True):
            for key in ("url", "body_text"):
                with pytest.raises(ValueError, match="missing_env_secrets"):
                    await run_api_contract_checks(http_client=client, domain="fixture", base_url="u",
                                                  checks=[{key: "${API_ABSENT}"}])
            results = await run_api_contract_checks(http_client=client, domain="fixture", base_url="u",
                checks=[{"headers": {"X-Fixture": "${API_ABSENT}"}}])
        request.assert_not_awaited()
        require(condition=not results[0].ok and results[0].status_code is None
                and results[0].error == "ValueError: missing_env_secrets: ['API_ABSENT']",
                message="header preparation escaped the original request failure scope")

    @staticmethod
    async def test_cancelled_request_does_not_continue_to_the_next_check() -> None:
        """A cancelled HTTP await propagates instead of being recorded as product failure."""
        request = AsyncMock(side_effect=asyncio.CancelledError)
        client = cast("AsyncClient", MagicMock(request=request))
        outcomes = await asyncio.gather(run_api_contract_checks(http_client=client, domain="fixture",
            base_url="u", checks=[{}, {}]), return_exceptions=True)
        require(condition=isinstance(outcomes[0], asyncio.CancelledError), message="cancellation consumed")
        request.assert_awaited_once()

    @staticmethod
    def test_path_admission_and_shared_substitution_keep_existing_rules() -> None:
        """Numeric list segments and uppercase environment references retain original validation."""
        for path in ("items.-1", "items.2", "items.bad", "items..0", "items.0.id."):
            require(condition=get_path({"items": [{"id": 3}]}, path) == (False, None), message="bad path admitted")
        require(condition=get_path({"items": [{"id": 3}]}, "items. 0 .id") == (True, 3),
                message="trimmed list index rejected")
        with patch.dict(os.environ, {"API_FIXTURE": "synthetic"}):
            require(condition=substitute_env_refs("${API_FIXTURE}/${lowercase}") == "synthetic/${lowercase}",
                    message="placeholder grammar changed")
