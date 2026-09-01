# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for scarce-resource API check coordination."""

from __future__ import annotations

import asyncio
import unittest
from collections import Counter
from typing import TYPE_CHECKING, final

from .metrics_api_contract import run_api_contract_checks

if TYPE_CHECKING:
    from .api_contract_models import ApiConfig, ApiContractCheckResult, ApiHttpResponse, ApiValue

_EXPECTED_SUCCESSES = 200


def _require(*, condition: bool, message: str) -> None:
    """Fail a regression test when its condition is false.

    Raises:
        AssertionError: The regression condition is false.
    """
    if not condition:
        raise AssertionError(message)


@final
class _FixtureResponse:
    def __init__(self, url: str, status_code: int) -> None:
        self.url: str = url
        self.status_code: int = status_code
        self.headers: dict[str, str] = {"content-type": "application/json"}

    def json(self) -> ApiValue:
        """Return a stable JSON fixture containing the request URL."""
        return {"status": "ok", "url": self.url}

    def read(self) -> bytes:
        """Return the buffered fixture body."""
        return self.url.encode()


@final
class _OneAccountClient:
    def __init__(self) -> None:
        self.active_leases = 0
        self.max_active_leases = 0
        self.contention_failures = 0
        self.successes: Counter[str] = Counter()
        self._state_lock = asyncio.Lock()

    async def request(self, *args: ApiValue, **kwargs: ApiValue) -> ApiHttpResponse:
        """Return 503 when a concurrent request holds the only account."""
        del kwargs
        url = str(args[1])
        async with self._state_lock:
            if self.active_leases:
                self.contention_failures += 1
                return _FixtureResponse(url, 503)
            self.active_leases += 1
            self.max_active_leases = max(self.max_active_leases, self.active_leases)
        await asyncio.sleep(0)
        async with self._state_lock:
            self.active_leases -= 1
            self.successes[url] += 1
        return _FixtureResponse(url, 200)

    async def aclose(self) -> None:
        """Close the in-memory fixture client."""


def _check(coordination_key: str | None) -> ApiConfig:
    check: ApiConfig = {
        "name": "codex_no_quota_readiness",
        "path": "/internal/monitor/codex-readiness",
        "expected_status_codes": [200],
    }
    if coordination_key is not None:
        check["coordination_key"] = coordination_key
    return check


async def _run_pair(
    client: _OneAccountClient,
    coordination_key: str | None,
) -> list[ApiContractCheckResult]:
    domains = ("afasask.gzb.nl", "demo.afasask.pitchai.net")
    paired = await asyncio.gather(
        *(
            run_api_contract_checks(
                http_client=client,
                domain=domain,
                base_url=f"https://{domain}",
                checks=[_check(coordination_key)],
                timeout_seconds=2.0,
            )
            for domain in domains
        ),
    )
    return [domain_results[0] for domain_results in paired]


class ApiContractCoordinationTests(unittest.IsolatedAsyncioTestCase):
    """Prove the regression and its keyed serialization fix."""

    async def test_uncoordinated_checks_contend_for_one_account(self) -> None:
        """Concurrent unkeyed probes reproduce one false 503 response."""
        test_name = self.id()
        client = _OneAccountClient()
        results = await _run_pair(client, None)
        observed_codes = (result.status_code for result in results)
        present_codes = (status_code for status_code in observed_codes if status_code is not None)
        status_codes = list(present_codes)
        success_values = (result.ok for result in results)
        success_count = sum(success_values)

        _require(
            condition=sorted(status_codes) == [200, 503],
            message=f"{test_name}: uncoordinated probes did not reproduce one 503",
        )
        _require(condition=success_count == 1, message="unexpected uncoordinated success count")
        _require(condition=client.contention_failures == 1, message="fixture missed one contention failure")

    async def test_keyed_checks_pass_one_hundred_paired_cycles(self) -> None:
        """A shared key serializes both probes without suppressing either."""
        test_name = self.id()
        client = _OneAccountClient()
        key = "afasask_auth_broker_readiness"
        for _cycle in range(100):
            results = await _run_pair(client, key)
            result_states = (result.ok for result in results)
            all_succeeded = all(result_states)
            result_keys = {result.coordination_key for result in results}
            wait_metrics = ("coordination_wait_ms" in result.details for result in results)
            all_waits_recorded = all(wait_metrics)
            _require(condition=all_succeeded, message=f"{test_name}: coordinated probe failed")
            _require(
                condition=result_keys == {key},
                message="result lost its coordination attribution",
            )
            _require(
                condition=all_waits_recorded,
                message="result omitted coordination wait telemetry",
            )

        _require(condition=client.contention_failures == 0, message="coordinated probes still contended")
        _require(condition=client.max_active_leases == 1, message="more than one account lease was active")
        success_count = sum(client.successes.values())
        _require(condition=success_count == _EXPECTED_SUCCESSES, message="not every coordinated probe executed")

    async def test_malformed_key_fails_closed(self) -> None:
        """An unsafe resource key cannot fall back to concurrent execution."""
        test_name = self.id()
        client = _OneAccountClient()
        result = (await _run_pair(client, "not SAFE"))[0]

        _require(condition=not result.ok, message=f"{test_name}: malformed coordination key passed")
        _require(condition=result.status_code is None, message="malformed key reached the HTTP client")
        _require(
            condition=(result.error or "").startswith("InvalidCoordinationKeyError:"),
            message="malformed key did not return the expected safe error",
        )
        _require(condition=sum(client.successes.values()) == 0, message="malformed key executed a request")
