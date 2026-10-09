# Copyright (c) 2026 PitchAI. All rights reserved.
"""Container identity and immediate status shared by inspection issue records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerStatus:
    """Keep the first four public fields and their positional construction order."""

    name: str
    container_id: str
    running: bool | None
    status: str | None
