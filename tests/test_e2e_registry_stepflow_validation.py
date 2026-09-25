# Copyright (c) 2026 PitchAI. All rights reserved.
"""StepFlow parsing and validation contract tests."""

from __future__ import annotations

import json

import pytest

from e2e_registry.stepflow import (
    StepFlowValidationError,
    parse_definition_bytes,
    validate_base_url,
    validate_definition,
)

_EXPECTED_STEP_COUNT = 2


def test_validate_base_url_accepts_http_https() -> None:
    """Accept and preserve both supported HTTP URL schemes.

    Raises:
        AssertionError: If URL validation alters a valid HTTP URL.
    """
    https_url = validate_base_url("https://example.com")
    if https_url != "https://example.com":
        message = f"HTTPS URL was not preserved: {https_url!r}"
        raise AssertionError(message)
    http_url = validate_base_url("http://127.0.0.1:8000")
    if http_url != "http://127.0.0.1:8000":
        message = f"HTTP URL was not preserved: {http_url!r}"
        raise AssertionError(message)


def test_validate_base_url_rejects_bad_scheme() -> None:
    """Reject non-HTTP browser target schemes."""
    with pytest.raises(StepFlowValidationError):
        validate_base_url("ftp://example.com")


def test_parse_and_validate_definition_json() -> None:
    """Parse JSON and preserve normalized name, count, and step type.

    Raises:
        AssertionError: If the normalized definition violates its contract.
    """
    raw = json.dumps(
        {
            "name": "t",
            "steps": [{"type": "goto"}, {"type": "expect_text", "text": "hi"}],
        },
    ).encode()
    definition = parse_definition_bytes(raw, content_type="application/json")
    normalized = validate_definition(definition)
    if normalized.get("name") != "t":
        message = f"unexpected normalized StepFlow name: {normalized.get('name')!r}"
        raise AssertionError(message)
    steps = normalized.get("steps")
    if not isinstance(steps, list) or len(steps) != _EXPECTED_STEP_COUNT:
        message = f"unexpected normalized StepFlow steps: {steps!r}"
        raise AssertionError(message)
    second_step = steps[1]
    if not isinstance(second_step, dict) or second_step.get("type") != "expect_text":
        message = f"unexpected second normalized StepFlow step: {second_step!r}"
        raise AssertionError(message)


def test_validate_definition_rejects_unknown_step_type() -> None:
    """Reject unrecognized StepFlow operation types."""
    with pytest.raises(StepFlowValidationError):
        validate_definition({"name": "t", "steps": [{"type": "nope"}]})


def test_validate_definition_rejects_fill_with_huge_literal_secret() -> None:
    """Reject oversized literal secrets in fill operations."""
    with pytest.raises(StepFlowValidationError):
        validate_definition(
            {
                "name": "t",
                "steps": [
                    {"type": "fill", "selector": "#pw", "text": "x" * 600},
                ],
            },
        )


def test_validate_definition_accepts_fill_with_secret_placeholder() -> None:
    """Accept a fill operation that references a runtime secret placeholder.

    Raises:
        AssertionError: If validation alters the secret placeholder.
    """
    normalized = validate_definition(
        {
            "name": "t",
            "steps": [
                {"type": "fill", "selector": "#pw", "text": "${PASSWORD}"},
            ],
        },
    )
    steps = normalized.get("steps")
    if not isinstance(steps, list) or not steps:
        message = f"normalized placeholder definition has no steps: {steps!r}"
        raise AssertionError(message)
    first_step = steps[0]
    if not isinstance(first_step, dict) or first_step.get("text") != "${PASSWORD}":
        message = f"secret placeholder was not preserved: {first_step!r}"
        raise AssertionError(message)
