# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared strict data contracts for domain-monitoring configuration and state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | Mapping[str, JsonValue] | Sequence[JsonValue]
type JsonObject = dict[str, JsonValue]
