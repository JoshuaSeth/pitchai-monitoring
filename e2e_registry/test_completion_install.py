# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reviewed source configuration cannot silently widen registry ownership."""

from __future__ import annotations

import json

import pytest

from .completion_install import reviewed_sources
from .test_completion_capture import expect_equal

_PAIR = {
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "test_id": "00000000-0000-4000-8000-000000000002",
}


def test_reviewed_pair_is_literal_and_empty_configuration_disables_capture() -> None:
    """A configured registry UUID never becomes an Engine tenant or project."""
    sources = reviewed_sources(json.dumps([_PAIR]))
    expect_equal(len(sources), 1)
    expect_equal(sources[0].tenant_id, _PAIR["tenant_id"])
    expect_equal(sources[0].test_id, _PAIR["test_id"])
    expect_equal(len(reviewed_sources("[]")), 0)


@pytest.mark.parametrize("document", [
    json.dumps([_PAIR, _PAIR]),
    json.dumps([{**_PAIR, "project_id": "unreviewed-engine-project"}]),
    json.dumps([{**_PAIR, "test_id": "*"}]),
    json.dumps([{**_PAIR, "tenant_id": "*"}]),
])
def test_invalid_or_broadened_sources_fail_closed(document: str) -> None:
    """Wildcards, implicit relationship fields and duplicate entries are rejected."""
    with pytest.raises(ValueError, match=r"."):
        _ = reviewed_sources(document)


@pytest.mark.parametrize("document", ["{}", json.dumps([{**_PAIR, "tenant_id": None}])])
def test_source_configuration_requires_explicit_string_pairs(document: str) -> None:
    """Malformed types cannot produce a partially interpreted source set."""
    with pytest.raises(TypeError, match=r"."):
        _ = reviewed_sources(document)
