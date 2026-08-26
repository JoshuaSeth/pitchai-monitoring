# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exercise evidence redaction and public-endpoint safety boundaries."""

from __future__ import annotations

import pytest

from domain_checks.monitoring_contracts.safe_evidence import (
    safe_public_url,
    safe_response_excerpt,
    safe_text_excerpt,
)
from monitoring_test_support.expectations import present


def test_safe_text_excerpt_removes_private_and_secret_material() -> None:
    """Redact private and credential-like values from operator evidence."""
    source = (
        '<script>window.secret="do-not-show"</script>'
        "contact ops@example.com "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456 "
        "token=super-private-value-123456 "
        "request 123e4567-e89b-42d3-a456-426614174000 "
        'name="Seth" phone=+31 6 1234 5678 upstream=10.0.0.8 path=/root/app/.env '
        "https://service.pitchai.net/failure?access_token=secret&email=ops@example.com "
        "upstream unavailable"
    )

    excerpt = safe_text_excerpt(source, max_chars=360)

    cleaned = present(excerpt, label="safe evidence unexpectedly disappeared")
    if "do-not-show" in cleaned:
        pytest.fail("script secret leaked")
    if "ops@example.com" in cleaned:
        pytest.fail("email leaked")
    if "super-private" in cleaned:
        pytest.fail("token leaked")
    if "123e4567" in cleaned:
        pytest.fail("request id leaked")
    if "Seth" in cleaned:
        pytest.fail("person name leaked")
    if "1234 5678" in cleaned:
        pytest.fail("phone number leaked")
    if "10.0.0.8" in cleaned:
        pytest.fail("private address leaked")
    if "/root/app/.env" in cleaned:
        pytest.fail("private path leaked")
    if "access_token" in cleaned:
        pytest.fail("query credential leaked")
    if "upstream unavailable" not in cleaned:
        pytest.fail("actionable failure evidence disappeared")
    if "[redacted" not in cleaned:
        pytest.fail("redaction marker disappeared")


def test_safe_public_url_rejects_non_http_and_strips_query_and_fragment() -> None:
    """Reject unsafe schemes and remove URL query, fragment, and identity data."""
    if safe_public_url("file:///etc/passwd") is not None:
        pytest.fail("file URL was accepted")
    if safe_public_url("https://dispatch.pitchai.net/ready?token=x#private") != "https://dispatch.pitchai.net/ready":
        pytest.fail("query or fragment survived URL sanitation")
    if (
        safe_public_url("https://dispatch.pitchai.net/users/owner%40example.com")
        != "https://dispatch.pitchai.net/users/redacted"
    ):
        pytest.fail("identity-bearing path survived URL sanitation")


def test_safe_response_excerpt_rejects_binary_and_redacts_text() -> None:
    """Reject binary bodies and sanitize bounded textual response evidence."""
    if safe_response_excerpt("secret", content_type="image/png") is not None:
        pytest.fail("binary response evidence was retained")
    excerpt = safe_response_excerpt(
        '{"error":"backend unavailable","email":"owner@example.com","token":"private-value-123456"}',
        content_type="application/problem+json; charset=utf-8",
    )
    cleaned = present(excerpt, label="safe textual response evidence disappeared")
    if "backend unavailable" not in cleaned:
        pytest.fail("actionable response evidence disappeared")
    if "owner@example.com" in cleaned:
        pytest.fail("response email leaked")
    if "private-value" in cleaned:
        pytest.fail("response token leaked")
