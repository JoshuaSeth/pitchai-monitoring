# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression proof for bounded retained-history dashboard projection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import json_types
from .domain_trends import history_for_domain
from .reliability_metrics import samples_for_group
from .testing_runtime import pytest

if TYPE_CHECKING:
    from .json_types import JsonObject, JsonValue
    from .testing_runtime import MonkeyPatch


def test_history_projection_never_renormalizes_retained_state(
    monkeypatch: MonkeyPatch,
) -> None:
    """Read normalized samples by reference instead of copying all history."""
    now_ts = 2_000_000_000.0
    target_sample: list[JsonValue] = [now_ts - 30, True, 125.0, 250.0, 200]
    state: JsonObject = {
        "history": {
            "target.pitchai.net": [target_sample],
            **{f"unrelated-{index}.pitchai.net": [[now_ts - 60, True, 10.0, 20.0, 200]] for index in range(256)},
        },
    }
    domains: list[JsonObject] = [
        {
            "domain": "target.pitchai.net",
            "group": "target",
            "disabled": False,
        },
    ]

    def reject_recursive_normalization(_value: json_types.JsonInput) -> json_types.JsonValue:
        pytest.fail("retained history crossed the recursive JSON normalizer")

    monkeypatch.setattr(json_types, "normalize_json", reject_recursive_normalization)

    samples = samples_for_group(
        domains,
        group_id="target",
        state=state,
        now_ts=now_ts,
    )
    domain_history = history_for_domain(state, "target.pitchai.net")

    if samples != [target_sample] or domain_history != [target_sample]:
        pytest.fail("normalized retained history changed during projection")
    if domain_history[0] is not target_sample:
        pytest.fail("retained history was copied instead of read by reference")
