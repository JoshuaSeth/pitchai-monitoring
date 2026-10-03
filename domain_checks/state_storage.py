# Copyright (c) 2026 PitchAI. All rights reserved.
"""File boundary for legacy monitor state, preserving read fallback and writes."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from .event_bus_delivery import JsonObject, JsonValue

_LOGGER = logging.getLogger("service-monitoring")


@dataclass
class _StateReadBoundary:
    """Own the existing warning/default policy at the actual file-read edge."""

    path: Path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, _error_type: type[BaseException] | None, error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        if not isinstance(error, Exception):
            return False
        if not isinstance(error, FileNotFoundError):
            _LOGGER.warning("Failed to read state file path=%s error=%s", self.path, error)
        return True


def read_state_value(path: Path) -> JsonValue:
    """Read only the requested JSON state file using the existing fallback.

    Returns:
        Decoded JSON, or None after an absent/unreadable/malformed state file.
        Missing files remain silent; other read errors retain the warning.
    """
    with _StateReadBoundary(path):
        # json.loads produces precisely the JSON primitive/container union.
        return cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    return None


def write_state_atomic(path: Path, payload: JsonObject) -> None:
    """Write sorted JSON through the same sibling temporary file and replace.

    File creation, serialization and replacement errors propagate to the cycle's
    existing write-failure handling; this boundary does not turn them healthy.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    _ = temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    _ = temporary.replace(path)
