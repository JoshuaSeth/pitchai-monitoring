# Copyright (c) 2026 PitchAI. All rights reserved.
"""Funding capture uses the same usage response and never widens HTTP authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import patch
from uuid import uuid4

from .expiry_source import ExpiryAwareSource
from .models import AccountDescriptor
from .test_organization_reset_policy import evaluate
from .test_organization_support import NOW, require, require_equal

if TYPE_CHECKING:
    from .funded_transport import JsonValue


@dataclass
class UsageTransport:
    """Fixed endpoint responses with a complete record of attempted HTTP authority."""

    usage: dict[str, JsonValue]
    calls: list[str] = field(default_factory=list)
    access_token: str = field(default_factory=lambda: uuid4().hex)

    def request(
        self, *, method: str, url: str, endpoint: str, headers: dict[str, str],
        **_options: dict[str, JsonValue] | bool | None,
    ) -> dict[str, JsonValue]:
        """Respond only to the existing read/probe path; unexpected mutations fail.

        Returns:
            A synthetic response from the named endpoint.
        """
        self.calls.append(endpoint)
        expected_method = "POST" if endpoint == "broker_analytics_probe" else "GET"
        require_equal(method, expected_method)
        require(condition=url.startswith(("http://broker.invalid/", "https://chatgpt.com/backend-api/")),
                message="unexpected destination")
        responses: dict[str, dict[str, JsonValue]] = {
            "broker_analytics_probe": {"state": {"availability": "rate_limited"}},
            "broker_export_auth": {"tokens": {"access_token": self.access_token, "account_id": "tenant-original"}},
            "provider_usage": self.usage,
            "provider_reset_credits": {"available_count": 0, "credits": []},
            "broker_execution_evidence": {"state": {}},
        }
        if endpoint.startswith("provider_"):
            require_equal(headers["ChatGPT-Account-Id"], "tenant-original")
            require_equal(headers["Authorization"], f"Bearer {self.access_token}")
        return responses[endpoint]


def test_source_captures_same_response_without_extra_calls_or_account_leakage() -> None:
    """Funding changes replace prior evidence and reset counts never become spend balances."""
    usage: dict[str, JsonValue] = {
        "rate_limit": {"allowed": False, "limit_reached": True, "primary_window": {
            "limit_window_seconds": 604800, "used_percent": 100, "reset_at": int(NOW.timestamp()) + 518400,
        }},
        "credits": {"has_credits": True, "unlimited": False, "balance": "62206.32859"},
        "model_usage": {"gpt-6-astra": {"available": True, "credits_would_enable": False}},
        "spend_control": {"reached": False, "individual_limit": None},
        "email": "private-payload-marker",
    }
    transport = UsageTransport(usage)
    source = ExpiryAwareSource(broker_url="http://broker.invalid", broker_admin_token=uuid4().hex, http=transport)
    descriptor = AccountDescriptor(broker_account_id="broker:test", label="test-account", enabled=True)
    with (
        patch("auth_reset_guardian.clients.utc_now", return_value=NOW),
        patch("auth_reset_guardian.expiry_source.read_subscription_expiry", return_value={}),
    ):
        funded = source.refresh_account(descriptor)
        require_equal(evaluate(funded).state, "indeterminate")
        del usage["credits"]
        usage["model_usage"] = None
        legacy = source.refresh_account(descriptor)
        require_equal(evaluate(legacy).state, "no_eligible_credit")
    expected_calls = [
        "broker_analytics_probe", "broker_export_auth", "provider_usage",
        "provider_reset_credits", "broker_execution_evidence",
    ]
    require_equal(tuple(transport.calls), tuple(expected_calls * 2))
    require(condition=cast("object", funded.usage_state["funded_capacity"]) == {
        "credits": "possible", "models": "possible", "spend_control": "none",
    }, message="funded classification was not retained from the original payload")
    for private in ("private-payload-marker", transport.access_token, "tenant-original", "62206.32859"):
        require_equal(private in json.dumps(funded.sanitized()), expected=False)
