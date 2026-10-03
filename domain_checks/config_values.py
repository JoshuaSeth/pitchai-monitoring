# Copyright (c) 2026 PitchAI. All rights reserved.
"""Values accepted at the existing YAML inventory boundary."""

from __future__ import annotations

from datetime import date, datetime

type ConfigValue = (
    str | bytes | int | float | bool | date | datetime | list[ConfigValue] | dict[str, ConfigValue] | None
)
