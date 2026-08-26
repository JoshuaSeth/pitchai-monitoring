# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protect the E2E registry from unapproved browser destinations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from domain_checks.json_types import json_object, text_value
from monitoring_test_support.base_url_policy import (
    bootstrap_policy_client,
    patch_test_base_url,
    response_object,
    upload_browser_test,
)

if TYPE_CHECKING:
    from pathlib import Path

    from domain_checks.json_types import JsonInput

_HTTP_BAD_REQUEST = 400
_HTTP_OK = 200


def _require_detail(response_text: str, expected: str) -> None:
    """Require one exact JSON error detail."""
    payload = json_object(cast("JsonInput", json.loads(response_text)))
    if text_value(payload.get("detail")) != expected:
        pytest.fail(f"unexpected base-URL policy response: {payload!r}")


def test_production_inventory_domain_is_accepted_when_enabled(tmp_path: Path) -> None:
    """Expand strict allowlisting from the canonical monitored inventory."""
    policy = bootstrap_policy_client(tmp_path, allow_monitored_domains=True)
    with policy.client:
        response = upload_browser_test(
            policy,
            name="monitored-production-domain",
            base_url="https://formatief-toetsen.pitchai.net",
        )
    if response.status_code != _HTTP_OK:
        pytest.fail(f"monitored production domain was rejected: {response.text}")


def test_reserved_and_unmonitored_domains_are_rejected(tmp_path: Path) -> None:
    """Reject reserved examples and non-allowlisted production-looking hosts."""
    policy = bootstrap_policy_client(tmp_path, allow_monitored_domains=False)
    with policy.client:
        reserved = upload_browser_test(
            policy,
            name="reserved-example-domain",
            base_url="https://example.com",
        )
        unlisted = upload_browser_test(
            policy,
            name="unlisted-domain",
            base_url="https://not-allowlisted.pitchai.net",
        )
    if reserved.status_code != _HTTP_BAD_REQUEST or unlisted.status_code != _HTTP_BAD_REQUEST:
        pytest.fail("strict base-URL policy accepted a forbidden destination")
    _require_detail(reserved.text, "base_url_not_allowed_host")
    _require_detail(unlisted.text, "base_url_not_monitored_domain")


def test_allowlisted_upload_cannot_be_patched_to_reserved_domain(tmp_path: Path) -> None:
    """Reapply strict policy when an existing test changes destination."""
    policy = bootstrap_policy_client(tmp_path, allow_monitored_domains=False)
    with policy.client:
        uploaded = upload_browser_test(
            policy,
            name="allowed-domain",
            base_url="https://autopar.pitchai.net",
        )
        if uploaded.status_code != _HTTP_OK:
            pytest.fail(f"explicitly allowlisted domain was rejected: {uploaded.text}")
        test_object = json_object(response_object(uploaded).get("test"))
        test_id = text_value(test_object.get("id"))
        patched = patch_test_base_url(policy, test_id=test_id, base_url="https://example.com")
    if patched.status_code != _HTTP_BAD_REQUEST:
        pytest.fail("existing test accepted a reserved base URL")
    _require_detail(patched.text, "base_url_not_allowed_host")
