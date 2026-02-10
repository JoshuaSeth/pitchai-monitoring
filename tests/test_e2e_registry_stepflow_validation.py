from __future__ import annotations

import json

import pytest

from e2e_registry.stepflow import StepFlowValidationError, parse_definition_bytes, validate_base_url, validate_definition


def test_validate_base_url_accepts_http_https() -> None:
    assert validate_base_url("https://example.com") == "https://example.com"
    assert validate_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


def test_validate_base_url_rejects_bad_scheme() -> None:
    with pytest.raises(StepFlowValidationError):
        validate_base_url("ftp://example.com")


def test_parse_and_validate_definition_json() -> None:
    raw = json.dumps({"name": "t", "steps": [{"type": "goto"}, {"type": "expect_text", "text": "hi"}]}).encode("utf-8")
    d = parse_definition_bytes(raw, content_type="application/json")
    out = validate_definition(d)
    assert out["name"] == "t"
    assert len(out["steps"]) == 2
    assert out["steps"][1]["type"] == "expect_text"


def test_validate_definition_rejects_unknown_step_type() -> None:
    with pytest.raises(StepFlowValidationError):
        validate_definition({"name": "t", "steps": [{"type": "nope"}]})


def test_validate_definition_rejects_fill_with_huge_literal_secret() -> None:
    with pytest.raises(StepFlowValidationError):
        validate_definition(
            {
                "name": "t",
                "steps": [
                    {"type": "fill", "selector": "#pw", "text": "x" * 600},
                ],
            }
        )


def test_validate_definition_accepts_fill_with_secret_placeholder() -> None:
    out = validate_definition(
        {
            "name": "t",
            "steps": [
                {"type": "fill", "selector": "#pw", "text": "${PASSWORD}"},
            ],
        }
    )
    assert out["steps"][0]["text"] == "${PASSWORD}"

