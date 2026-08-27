# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit local-network gateway for monitoring browser fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from socket import AF_INET, SOCK_STREAM
from socket import socket as open_socket
from typing import TYPE_CHECKING, Protocol, cast

from httpx import AsyncClient

if TYPE_CHECKING:
    from httpx import Response


class DashboardLocation(Protocol):
    """Connection details required by the local dashboard gateway."""

    @property
    def base_url(self) -> str:
        """Return the local dashboard origin."""
        raise NotImplementedError

    @property
    def monitor_token(self) -> str:
        """Return the isolated machine token."""
        raise NotImplementedError


@dataclass(frozen=True)
class HttpReceipt:
    """Status and body retained from one local dashboard request."""

    status_code: int
    text: str


@dataclass(frozen=True)
class IdentityReceipts:
    """Denied or absent dashboard identity route receipts."""

    anonymous: HttpReceipt
    wrong_tenant: HttpReceipt
    browser_with_token: HttpReceipt
    login: HttpReceipt


@dataclass(frozen=True)
class AuthorizedRouteReceipts:
    """Authorized data and static-asset route receipts."""

    browser_summary: HttpReceipt
    machine_summary: HttpReceipt
    stylesheet: HttpReceipt
    script: HttpReceipt


@dataclass(frozen=True)
class DashboardContractReceipts:
    """All requests needed to prove the dashboard authentication boundary."""

    identity: IdentityReceipts
    authorized: AuthorizedRouteReceipts


def _receipt(response: Response) -> HttpReceipt:
    return HttpReceipt(status_code=response.status_code, text=response.text)


def free_tcp_port() -> int:
    """Reserve and release one loopback port for an immediate fixture bind.

    Returns:
        The available TCP port number.
    """
    socket_factory = partial(open_socket, AF_INET, SOCK_STREAM)
    with socket_factory() as listener:
        listener.bind(("127.0.0.1", 0))
        address = cast("tuple[str, int]", listener.getsockname())
        return address[1]


async def fetch_dashboard_contract(server: DashboardLocation) -> DashboardContractReceipts:
    """Fetch browser, machine, identity, and static-asset boundaries.

    Returns:
        Typed receipts for every requested route.
    """
    client_factory = partial(AsyncClient, base_url=server.base_url)
    async with client_factory() as client:
        anonymous = await client.get("/dashboard")
        wrong_tenant = await client.get(
            "/dashboard",
            headers={"X-PitchAI-Email": "operator@example.com"},
        )
        browser_summary = await client.get(
            "/dashboard/api/v1/monitoring/summary",
            headers={"X-PitchAI-Email": "operator@pitchai.net"},
        )
        machine_summary = await client.get(
            "/api/v1/monitoring/summary",
            headers={"Authorization": f"Bearer {server.monitor_token}"},
        )
        browser_with_token = await client.get(
            "/dashboard/api/v1/monitoring/summary",
            headers={"Authorization": f"Bearer {server.monitor_token}"},
        )
        login = await client.get("/dashboard/login")
        stylesheet = await client.get("/dashboard/assets/monitoring-dashboard.css")
        script = await client.get("/dashboard/assets/monitoring-dashboard.js")
    return DashboardContractReceipts(
        identity=IdentityReceipts(
            anonymous=_receipt(anonymous),
            wrong_tenant=_receipt(wrong_tenant),
            browser_with_token=_receipt(browser_with_token),
            login=_receipt(login),
        ),
        authorized=AuthorizedRouteReceipts(
            browser_summary=_receipt(browser_summary),
            machine_summary=_receipt(machine_summary),
            stylesheet=_receipt(stylesheet),
            script=_receipt(script),
        ),
    )
