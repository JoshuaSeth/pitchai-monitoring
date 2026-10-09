# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated dashboard loading, normalization and summary compatibility contracts."""

from __future__ import annotations

import json
import math
import unittest
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from domain_checks.dft_test_support import require

from .dashboard_data import load_json, load_monitor_data, load_yaml
from .dashboard_inventory import normalize_domain_entries, normalize_domain_groups
from .dashboard_values import downsample, history_range_utc, safe_float, safe_int, safe_timestamp

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue


class DashboardInputTests(unittest.TestCase):
    """Private files and deterministic values; no monitor/registry service startup."""

    @staticmethod
    def test_loading_retains_history_and_config_error_order() -> None:
        """History normalization still precedes state-error evaluation."""
        with TemporaryDirectory(prefix="dashboard-input-test-") as directory:
            state = Path(directory) / "state.json"
            config = Path(directory) / "config.yaml"
            with patch("time.time", return_value=120.0):
                data = load_monitor_data(state_path=str(state), config_path=str(config))
            require(condition=data.state == {"history": {}}, message="history fallback changed")
            require(condition=data.state_error == f"missing_or_invalid_config: {config}",
                    message="loader error precedence changed")
            require(condition=math.isclose(data.loaded_at_ts, 120.0), message="snapshot clock changed")
            for field in fields(data):
                with pytest.raises(FrozenInstanceError):
                    setattr(data, field.name, "mutation")

    @staticmethod
    def test_normalized_history_and_yaml_dates_are_preserved() -> None:
        """Parsing changes neither input bytes nor mtime, and does not flatten dates."""
        with TemporaryDirectory(prefix="dashboard-input-test-") as directory:
            state = Path(directory) / "state.json"
            config = Path(directory) / "config.yaml"
            raw = {"history": {"a.invalid": [[2, False, "bad"], [1, True, 20, 30, 200]]}}
            _ = state.write_text(json.dumps(raw), encoding="utf-8")
            _ = config.write_text("reviewed_at: 2026-10-04\ndomains: [a.invalid]\n", encoding="utf-8")
            before = state.read_bytes(), config.read_bytes(), state.stat().st_mtime_ns, config.stat().st_mtime_ns
            data = load_monitor_data(state_path=str(state), config_path=str(config))
            expected = {"a.invalid": [[1.0, True, 20.0, 30.0, 200], [2.0, False, None, None, None]]}
            require(condition=data.state["history"] == expected, message="normalized history changed")
            require(condition=str(data.config["reviewed_at"]) == "2026-10-04", message="YAML date changed")
            after = state.read_bytes(), config.read_bytes(), state.stat().st_mtime_ns, config.stat().st_mtime_ns
            require(condition=before == after, message="dashboard loader mutated inputs")

    @staticmethod
    def test_loader_fallback_includes_decoder_and_ordinary_io_errors() -> None:
        """The display's empty fallback remains separate from monitor startup validation."""
        for error in (OSError("synthetic"), ValueError("decoder"), RecursionError("nested")):
            with patch.object(Path, "read_text", side_effect=error):
                require(condition=load_json(Path("synthetic")) == {}, message="JSON fallback changed")
                require(condition=load_yaml(Path("synthetic")) == {}, message="YAML fallback changed")

    @staticmethod
    def test_inventory_normalizes_all_entries_before_deduplication() -> None:
        """A bad policy on a later duplicate must not disappear during deduplication."""
        normalized = normalize_domain_entries([" a.invalid ", {"domain": "a.invalid", "disabled": True}, "b.invalid"])
        domains = [item["domain"] for item in normalized]
        require(condition=domains == ["a.invalid", "b.invalid"], message="domain ordering changed")
        require(condition=normalized[0]["disabled"] is False, message="first duplicate replaced")
        invalid: list[ConfigValue] = [
            "a.invalid", {"domain": "a.invalid", "alert_policy": {"telegram": "dashboard-only"}},
        ]
        with pytest.raises(ValueError, match=r"domains\[1\].alert_policy.reason"):
            normalize_domain_entries(invalid)

    @staticmethod
    def test_group_sorting_and_invalid_order_keep_prior_policy() -> None:
        """Only TypeError/ValueError use the fallback; infinity still raises."""
        groups = normalize_domain_groups({"zed": {"order": "bad"}, "beta": {"order": 1}, "alpha": {"order": 1}})
        identifiers = [item["id"] for item in groups]
        require(condition=identifiers == ["alpha", "beta", "zed"], message="group sorting changed")
        with pytest.raises(OverflowError):
            normalize_domain_groups({"bad": {"order": math.inf}})

    @staticmethod
    def test_numeric_time_and_downsampling_boundaries() -> None:
        """Do not fabricate finite values, timestamps or new endpoint identities."""
        require(condition=safe_int(math.inf) is None and safe_float([]) is None, message="invalid scalar changed")
        require(condition=safe_float(math.inf) == math.inf, message="nonfinite float changed")
        expected = datetime(2026, 10, 4, tzinfo=UTC).timestamp()
        require(condition=safe_timestamp("2026-10-04T00:00:00") == expected, message="naive UTC timestamp changed")
        require(condition=safe_timestamp(-1) is None, message="nonpositive timestamp accepted")
        items = [[0], [1], [2], [3], [4], [5], [6], [7], [8], [9]]
        require(condition=downsample(items, max_points=10) is items, message="short-list identity changed")
        selected = downsample(items, max_points=3)
        require(condition=selected == [items[0], items[4], items[8], items[9]], message="sampling stride changed")
        require(condition=selected[-1] is items[-1], message="last item copied")
        require(condition=history_range_utc({"a": [[5], [3]], "bad": [[]]}) == (5.0, 3.0),
                message="existing endpoint-only history range changed")
