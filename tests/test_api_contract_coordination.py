# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for scarce-resource API contract coordination."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from domain_checks.api_contract_coordination import ApiContractCoordinator
from domain_checks.main import _update_effective_ok
from domain_checks.metrics_api_contract import (
    ApiContractCheckResult,
    api_contract_alert_batch_key,
    run_api_contract_checks,
)


class _OneAccountBroker:
    def __init__(self, *, available_accounts: int = 1, manual_release: bool = True) -> None:
        self.available_accounts = available_accounts
        self.active_leases = 0
        self.max_active_leases = 0
        self.contention_failures = 0
        self.no_capacity_failures = 0
        self.successes_by_host: dict[str, int] = {}
        self.first_lease_acquired = asyncio.Event()
        self.contention_observed = asyncio.Event()
        self._manual_release = manual_release
        self._release_lease = asyncio.Event()
        self._state_lock = asyncio.Lock()

    async def handle(self, request: httpx.Request) -> httpx.Response:
        async with self._state_lock:
            if self.available_accounts == 0:
                if self.active_leases:
                    self.contention_failures += 1
                    self.contention_observed.set()
                else:
                    self.no_capacity_failures += 1
                return httpx.Response(
                    503,
                    request=request,
                    json={"status": "fail", "pool": {"selectable_accounts": 0}},
                )
            self.available_accounts -= 1
            self.active_leases += 1
            self.max_active_leases = max(self.max_active_leases, self.active_leases)
            self.first_lease_acquired.set()
        if self._manual_release:
            await self._release_lease.wait()
        else:
            await asyncio.sleep(0)
        async with self._state_lock:
            self.active_leases -= 1
            self.available_accounts += 1
            host = request.url.host
            self.successes_by_host[host] = self.successes_by_host.get(host, 0) + 1
        return httpx.Response(
            200,
            request=request,
            json={
                "status": "ok",
                "quota_used": False,
                "prompt_submitted": False,
                "generation_started": False,
                "afasask": {"temp_codex_home_materialized": True},
                "broker_canary": {
                    "status": "ok",
                    "response": {"status": "ok", "pool": {"selectable_accounts": 1}},
                },
            },
        )

    def release_lease(self) -> None:
        self._release_lease.set()

    def restore_one_account(self) -> None:
        if self.active_leases != 0:
            raise RuntimeError("cannot restore capacity while a fixture lease is active")
        self.available_accounts = 1


async def _run_readiness(
    client: httpx.AsyncClient,
    *,
    coordinator: ApiContractCoordinator,
    coordination_key: str | None,
    domain: str,
) -> list[ApiContractCheckResult]:
    check = {
        "name": "codex_no_quota_readiness",
        "path": "/internal/monitor/codex-readiness",
        "expected_status_codes": [200],
        "json_paths_equal": {
            "status": "ok",
            "quota_used": False,
            "prompt_submitted": False,
            "generation_started": False,
            "afasask.temp_codex_home_materialized": True,
            "broker_canary.status": "ok",
            "broker_canary.response.status": "ok",
        },
    }
    if coordination_key is not None:
        check["coordination_key"] = coordination_key
    return await run_api_contract_checks(
        http_client=client,
        domain=domain,
        base_url=f"https://{domain}",
        checks=[check],
        coordinator=coordinator,
        timeout_seconds=2.0,
    )


async def _run_pair(
    client: httpx.AsyncClient,
    coordinator: ApiContractCoordinator,
    *,
    coordination_key: str | None,
) -> list[ApiContractCheckResult]:
    paired = await asyncio.gather(
        _run_readiness(
            client,
            coordinator=coordinator,
            coordination_key=coordination_key,
            domain="afasask.gzb.nl",
        ),
        _run_readiness(
            client,
            coordinator=coordinator,
            coordination_key=coordination_key,
            domain="demo.afasask.pitchai.net",
        ),
    )
    return [domain_results[0] for domain_results in paired]


@pytest.mark.asyncio
async def test_uncoordinated_scheduler_has_one_winner_and_one_loser() -> None:
    broker = _OneAccountBroker()
    transport = httpx.MockTransport(broker.handle)
    coordinator = ApiContractCoordinator()
    async with httpx.AsyncClient(transport=transport) as client:
        tasks = [
            asyncio.create_task(
                _run_readiness(
                    client,
                    coordinator=coordinator,
                    coordination_key=None,
                    domain=domain,
                )
            )
            for domain in ("afasask.gzb.nl", "demo.afasask.pitchai.net")
        ]
        try:
            await asyncio.wait_for(broker.first_lease_acquired.wait(), timeout=1.0)
            await asyncio.wait_for(broker.contention_observed.wait(), timeout=1.0)
        finally:
            broker.release_lease()
        results_by_domain = await asyncio.gather(*tasks)
    results = [domain_results[0] for domain_results in results_by_domain]
    assert sorted(result.status_code for result in results if result.status_code is not None) == [200, 503]
    assert sum(result.ok for result in results) == 1
    assert broker.contention_failures == 1
    assert broker.no_capacity_failures == 0
    assert broker.active_leases == 0
    assert broker.available_accounts == 1


@pytest.mark.asyncio
async def test_coordinated_one_account_fixture_passes_100_paired_cycles() -> None:
    broker = _OneAccountBroker(manual_release=False)
    coordinator = ApiContractCoordinator()
    transport = httpx.MockTransport(broker.handle)
    async with httpx.AsyncClient(transport=transport) as client:
        for _cycle in range(100):
            results = await _run_pair(
                client,
                coordinator,
                coordination_key="afasask_auth_broker_readiness",
            )
            assert all(result.ok for result in results)
            assert [result.domain for result in results] == [
                "afasask.gzb.nl",
                "demo.afasask.pitchai.net",
            ]
            assert {result.coordination_key for result in results} == {"afasask_auth_broker_readiness"}
            assert all(
                set(result.details) == {"content_type", "coordination_wait_ms", "final_url"}
                for result in results
            )
            assert broker.active_leases == 0
            assert broker.available_accounts == 1

    assert broker.contention_failures == 0
    assert broker.no_capacity_failures == 0
    assert broker.max_active_leases == 1
    assert broker.successes_by_host == {
        "afasask.gzb.nl": 100,
        "demo.afasask.pitchai.net": 100,
    }


@pytest.mark.asyncio
async def test_zero_capacity_fails_closed_once_and_recovers_after_restoration() -> None:
    broker = _OneAccountBroker(available_accounts=0, manual_release=False)
    coordinator = ApiContractCoordinator()
    transport = httpx.MockTransport(broker.handle)
    states = {
        "afasask.gzb.nl": (True, 0, 0),
        "demo.afasask.pitchai.net": (True, 0, 0),
    }
    degradation_batches: dict[str, list[ApiContractCheckResult]] = {}
    async with httpx.AsyncClient(transport=transport) as client:
        for cycle in range(4):
            if cycle == 2:
                broker.restore_one_account()
            results = await _run_pair(
                client,
                coordinator,
                coordination_key="afasask_auth_broker_readiness",
            )
            for result in results:
                prev_ok, fail_streak, success_streak = states[result.domain]
                next_ok, next_fail, next_success, alerted = _update_effective_ok(
                    prev_effective_ok=prev_ok,
                    observed_ok=result.ok,
                    fail_streak=fail_streak,
                    success_streak=success_streak,
                    down_after_failures=2,
                    up_after_successes=2,
                )
                states[result.domain] = (next_ok, next_fail, next_success)
                if alerted:
                    batch_key = api_contract_alert_batch_key(result.domain, [result])
                    degradation_batches.setdefault(batch_key, []).append(result)

            expected_effective_ok = cycle < 1 or cycle == 3
            assert all(state[0] is expected_effective_ok for state in states.values())

    assert len(degradation_batches) == 1
    degradation = degradation_batches["resource:afasask_auth_broker_readiness"]
    assert {result.domain for result in degradation} == set(states)
    assert broker.contention_failures == 0
    assert broker.no_capacity_failures == 4
    assert broker.active_leases == 0
    assert broker.available_accounts == 1
