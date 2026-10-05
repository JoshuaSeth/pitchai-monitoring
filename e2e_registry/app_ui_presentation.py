# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing best-effort registry display conversions and confined source preview."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .dashboard_records import integer

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .dashboard_records import Record

_PREVIEW_LIMIT = 80_000


def normalize_display_tests(tests: list[Record]) -> None:
    """Preserve in-place numeric normalization and each field's best-effort fallback."""
    for test in tests:
        for key in ("effective_ok", "fail_streak", "success_streak"):
            # Display corruption keeps the original value; it never asserts health.
            with suppress(Exception):
                if test.get(key) is not None:
                    test[key] = integer(test[key])


def display_artifacts(value: ConfigValue) -> ConfigValue:
    """Decode the existing string/dictionary display values without imposing a new schema.

    Returns:
        The original truthy decoded value, or the existing empty display fallback.
    """
    if not isinstance(value, (str, dict)):
        return {}
    artifacts: ConfigValue = {}
    # The existing UI keeps malformed persisted JSON out of the template.
    with suppress(Exception):
        artifacts = cast("ConfigValue", json.loads(value)) if isinstance(value, str) else value
    return artifacts or {}


@dataclass
class SourcePreview:
    """A single source read; a known filename survives an ordinary read failure."""

    filename: str | None = None
    text: str | None = None

    def read(self, directory: str, test: Record) -> None:
        """Retain source confinement, replacement decoding and original text truncation."""
        kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
        relative = str(test.get("source_relpath") or "").strip()
        if kind == "stepflow" or not relative:
            return
        # Source previews are optional UI data; request/database errors stay loud.
        with suppress(Exception):
            base = Path(directory).resolve()
            source = (base / relative).resolve()
            if base in source.parents and source.exists() and source.is_file():
                self.filename = source.name
                self.text = source.read_text(encoding="utf-8", errors="replace")
                if len(self.text) > _PREVIEW_LIMIT:
                    self.text = self.text[:_PREVIEW_LIMIT] + "\n...truncated..."
