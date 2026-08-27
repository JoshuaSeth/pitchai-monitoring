# Copyright (c) 2026 PitchAI. All rights reserved.
"""Atomic state-file boundary for database dependency monitoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .json_types import json_object

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject


def load_state(path: Path) -> JsonObject:
    """Load retained state, treating only a genuinely absent first-run file as empty.

    Returns:
        The normalized retained state, or an empty first-run state.
    """
    if not path.exists():
        return {}
    decoded = cast("JsonInput", json.loads(path.read_text(encoding="utf-8")))
    return json_object(decoded)


def write_state(path: Path, state: JsonObject) -> None:
    """Replace the compact state file atomically on its mounted filesystem."""
    temporary = path.with_name(f".{path.name}.tmp")
    payload = json.dumps(state, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    _ = temporary.write_text(payload, encoding="utf-8")
    _ = Path(temporary).replace(path)
