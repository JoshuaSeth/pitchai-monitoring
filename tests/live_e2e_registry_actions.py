# Copyright (c) 2026 PitchAI. All rights reserved.
"""Mutation helpers for live E2E registry acceptance workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.live_e2e_registry_support import object_records, response_payload

if TYPE_CHECKING:
    import httpx


async def disable_test(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    test_id: str,
    disablement: tuple[str, float],
) -> None:
    """Disable one live acceptance test until the explicit timestamp."""
    reason, until_ts = disablement
    response_payload(
        await client.post(
            f"{registry_url.rstrip('/')}/api/v1/tests/{test_id}/disable",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"reason": reason, "until": until_ts},
            timeout=15.0,
        ),
        label=f"disable live test {test_id}",
    )


async def trigger_test(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    test_id: str,
) -> None:
    """Request immediate execution of one live acceptance test."""
    response_payload(
        await client.post(
            f"{registry_url.rstrip('/')}/api/v1/tests/{test_id}/run",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        ),
        label=f"trigger live test {test_id}",
    )


async def run_count(
    client: httpx.AsyncClient,
    *,
    registry_url: str,
    tenant_token: str,
    test_id: str,
) -> int:
    """Return the validated number of runs visible to one tenant."""
    payload = response_payload(
        await client.get(
            f"{registry_url.rstrip('/')}/api/v1/tests/{test_id}/runs",
            headers={"Authorization": f"Bearer {tenant_token}"},
            timeout=15.0,
        ),
        label=f"live runs for {test_id}",
    )
    return len(object_records(payload.get("runs"), label="live runs"))
