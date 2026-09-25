# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provide strict account and browser helpers for dashboard UI tests."""

from __future__ import annotations

import socket
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC as DATETIME_UTC
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Required, TypedDict, Unpack, final

from auth_usage_dashboard.json_contract import decode_document
from domain_checks.testing import verify
from tests.auth_test_contract import FixtureContractError, required_number

if TYPE_CHECKING:
    from playwright.async_api import Page

    from auth_usage_dashboard.json_contract import JsonObject, JsonValue

UTC = DATETIME_UTC

type StringEvaluator = Callable[[str], Awaitable[str]]
type SocketAddressReader = Callable[[], tuple[str, int]]


class UiAccountOptions(TypedDict, total=False):
    """Describe required and optional provider state for one UI account."""

    availability: Required[str]
    five_used: Required[float]
    weekly_used: Required[float]
    offset_minutes: Required[int]
    weekly_only: bool


def _string_evaluator(page: Page) -> StringEvaluator:
    """Constrain Playwright evaluation to serialized JSON text.

    Returns:
        The resulting value.

    """
    evaluator: StringEvaluator = page.evaluate
    return evaluator


def _socket_address_reader(sock: socket.socket) -> SocketAddressReader:
    """Constrain a bound socket to its IPv4 address operation.

    Returns:
        The resulting value.

    """
    reader: SocketAddressReader = sock.getsockname
    return reader


def free_port() -> int:
    """Reserve and release one local TCP port for the UI server fixture.

    Returns:
        The computed value.

    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return _socket_address_reader(sock)()[1]


def account_fixture(
    label: str,
    **options: Unpack[UiAccountOptions],
) -> JsonObject:
    """Build one dashboard account with a week of provider analytics.

    Returns:
        The resulting value.

    Raises:
        FixtureContractError: If the browser evaluator has an invalid type.

    """
    now = datetime.now(UTC)
    banked = options["offset_minutes"] % 4
    daily_usage: list[JsonValue] = []
    lifetime_tokens = 0
    for day in range(7):
        tokens = (day + 1) * 12_000 + options["offset_minutes"] * 40
        lifetime_tokens += tokens
        daily_usage.append(
            {
                "start_date": (now.date() - timedelta(days=6 - day)).isoformat(),
                "tokens": tokens,
            },
        )
    reset_details: list[JsonValue] = []
    if banked:
        reset_details.append(
            {
                "reset_type": "weekly",
                "status": "available",
                "granted_at": (now - timedelta(days=2)).isoformat(),
                "expires_at": (now + timedelta(days=8, hours=options["offset_minutes"] % 5)).isoformat(),
                "title": "Weekly usage reset",
            },
        )
    rate_limit: JsonObject = {
        "primary_window": {
            "used_percent": options["five_used"],
            "reset_at": (now + timedelta(minutes=options["offset_minutes"])).isoformat(),
            "limit_window_seconds": 18_000,
        },
        "secondary_window": {
            "used_percent": options["weekly_used"],
            "reset_at": (now + timedelta(days=5, hours=options["offset_minutes"] % 8)).isoformat(),
            "limit_window_seconds": 604_800,
        },
    }
    if options.get("weekly_only"):
        secondary_window = rate_limit["secondary_window"]
        if not isinstance(secondary_window, dict):
            msg = "secondary window fixture must be an object"
            raise FixtureContractError(msg)
        rate_limit = {"primary_window": secondary_window}
    return {
        "metadata": {
            "account_id": f"internal-{options['offset_minutes']}",
            "label": label,
            "enabled": True,
            "prefer_for_all_clients": label == "svxjvmk78b@privaterelay.appleid.com",
        },
        "state": {
            "availability": options["availability"],
            "last_probe_at": (now - timedelta(seconds=22)).isoformat(),
            "usage": {
                "email": label,
                "plan_type": "pro",
                "rate_limit": rate_limit,
                "rate_limit_reset_credits": {"available_count": banked},
            },
            "analytics": {
                "last_probe_at": (now - timedelta(seconds=35)).isoformat(),
                "token_usage_updated_at": (now - timedelta(seconds=35)).isoformat(),
                "token_usage": {
                    "summary": {"lifetime_tokens": lifetime_tokens},
                    "daily_usage_buckets": daily_usage,
                },
                "reset_credits_updated_at": (now - timedelta(seconds=35)).isoformat(),
                "reset_credits": {
                    "available_count": banked,
                    "credits": reset_details,
                },
                "errors": {},
            },
        },
    }


@final
class FixtureSource:
    """Serve the fixed eight-account browser fixture."""

    def __init__(self) -> None:
        """Build the UI account portfolio."""
        self.accounts = _fixture_accounts()
        self.closed = False

    def read_accounts(self) -> list[JsonObject]:
        """Return an isolated copy of the fixture accounts."""
        return deepcopy(self.accounts)

    @staticmethod
    def probe_accounts(accounts: list[JsonObject]) -> dict[str, str]:
        """Return a successful no-op legacy probe result."""
        _ = accounts
        return {}

    @staticmethod
    def probe_analytics(accounts: list[JsonObject]) -> dict[str, str]:
        """Return a successful no-op analytics probe result."""
        _ = accounts
        return {}

    def close(self) -> None:
        """Record source closure."""
        self.closed = True


def _fixture_accounts() -> list[JsonObject]:
    """Build the representative eight-account browser portfolio.

    Returns:
        The resulting collection.

    """
    account_specs = (
        ("elise@pitchai.net", "available", 38.0, 31.0, 252),
        ("info@pitchai.net", "auth_invalid", 100.0, 45.0, 55),
        ("jozuasethvanderbijl@gmail.com", "available", 17.0, 20.0, 214),
        ("onboarding.bigi.net", "available", 22.0, 32.0, 161),
        ("sales@pitchai.net", "auth_invalid", 100.0, 19.0, 34),
        ("seth.vanderbijl@pitchai.net", "available", 10.0, 25.0, 90),
        ("support@pitchai.net", "rate_limited", 4.0, 100.0, 298),
        ("svxjvmk78b@privaterelay.appleid.com", "available", 74.0, 12.0, 207),
    )
    accounts: list[JsonObject] = []
    for label, availability, five_used, weekly_used, offset_minutes in account_specs:
        accounts.append(
            account_fixture(
                label,
                availability=availability,
                five_used=five_used,
                weekly_used=weekly_used,
                offset_minutes=offset_minutes,
                weekly_only=True,
            ),
        )
    return accounts


async def assert_no_viewport_overflow(page: Page) -> None:
    """Require rendered document width to stay inside its viewport.

    Raises:
        FixtureContractError: If viewport dimensions violate their required shape.

    """
    encoded = await _string_evaluator(page)(
        """() => JSON.stringify({
          viewport: document.documentElement.clientWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth
        })""",
    )
    dimensions = decode_document(encoded)
    if not isinstance(dimensions, dict):
        msg = "viewport dimensions must be an object"
        raise FixtureContractError(msg)
    viewport = required_number(dimensions.get("viewport"), label="viewport width")
    document = required_number(dimensions.get("document"), label="document width")
    body = required_number(dimensions.get("body"), label="body width")
    verify(document <= viewport + 1)
    verify(body <= viewport + 1)
