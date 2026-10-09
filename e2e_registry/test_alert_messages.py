# Copyright (c) 2026 PitchAI. All rights reserved.
"""Pure registry text checks; no client, browser, database or transport."""

from __future__ import annotations

import json
import unittest
from typing import TYPE_CHECKING, cast

from domain_checks.dft_test_support import require
from domain_checks.message_templates import dispatch_read_only_rules

from . import alerts
from .alert_messages import artifact_names, public_url, safe_json
from .settings import RegistrySettings

if TYPE_CHECKING:
    from collections.abc import Callable

    from domain_checks.event_bus_delivery import JsonObject, JsonValue


class AlertMessageTests(unittest.TestCase):
    """Guard stable links, truncation, recognized artifacts and the shared safety text."""

    @staticmethod
    def test_shared_rules_are_same_callable_and_prompt_bytes() -> None:
        """Registry compatibility alias shares the actual monitor function."""
        alias = cast("Callable[[], str]", vars(alerts)["_dispatch_read_only_rules"])
        require(condition=alias is dispatch_read_only_rules,
                message="safety rules copied instead of shared")
        prompt = alerts.build_dispatch_prompt_for_failure(
            test_id="test", test_name="synthetic", base_url="https://fixture.invalid", run_id="run",
            error_kind=None, error_message=None, artifacts=None,
        )
        require(condition=prompt.count(dispatch_read_only_rules()) == 1, message="rules changed or repeated")
        require(condition='"test_kind": null' in prompt, message="default kind missing")

    @staticmethod
    def test_failure_optional_fields_and_artifact_order() -> None:
        """Keep debounce, text bounds and recognized nonblank artifact entries."""
        message = alerts.build_failure_telegram_message(
            settings=RegistrySettings(public_base_url="https://registry.invalid///"), tenant_id="unused",
            test_id="test", test_name="fixture", test_kind="k" * 41, run_id="run", fail_streak=4,
            down_after_failures=3, error_kind="e" * 121, error_message="m" * 501, final_url="u" * 801,
            artifacts={"run_log": "r", "failure_screenshot": "f", "trace_zip": " ", "other": "x"},
        )
        require(condition="Debounce: fail_streak=4/3" in message, message="debounce changed")
        for prefix, letter, length in (("Kind", "k", 40), ("Error kind", "e", 120),
                                       ("Error", "m", 500), ("Final URL", "u", 800)):
            require(condition=f"{prefix}: {letter * length}\n" in message, message=f"{prefix} bound changed")
        require(condition=message.endswith("Artifacts: failure_screenshot, run_log"), message="artifact order changed")
        require(condition="UI: https://registry.invalid/ui/runs/run" in message, message="run link changed")

    @staticmethod
    def test_links_and_recovery_preserve_relative_default() -> None:
        """No configured public base means no invented recipient or absolute URL."""
        settings = RegistrySettings(public_base_url="")
        require(condition=public_url(settings, "relative") == "relative", message="relative link changed")
        message = alerts.build_recovery_telegram_message(settings=settings, test_id="test",
                                                        test_name="fixture", run_id="run")
        require(condition=message == "External E2E test RECOVERED ✅\nTest: fixture\nTest ID: test\nRun: /ui/runs/run",
                message="recovery bytes changed")

    @staticmethod
    def test_json_truncation_unicode_and_circular_fallback() -> None:
        """Serialization and its existing circular-reference fallback remain bounded."""
        value: JsonObject = {"b": "é", "a": [True, None]}
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
        require(condition=safe_json(value) == rendered, message="JSON formatting changed")
        limit = 7
        require(condition=safe_json(value, max_len=limit) == rendered[:limit] + "\n...truncated...",
                message="truncation changed")
        circular: list[JsonValue] = []
        circular.append(circular)
        require(condition=safe_json(circular) == "[[...]]", message="circular fallback changed")
        require(condition=not artifact_names(cast("JsonValue", ["not an object"])), message="invalid artifacts used")
