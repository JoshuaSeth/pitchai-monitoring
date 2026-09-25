# Copyright (c) 2026 PitchAI. All rights reserved.
"""Local-runtime topology preflight for dropped-UID runner integration."""

from __future__ import annotations

import stat
import sys
from pathlib import Path


class UnsupportedSandboxRuntimeTopologyError(RuntimeError):
    """Raised when a dropped UID cannot enter the local runner runtime."""


def sandbox_runtime_topology_issue() -> str | None:
    """Return why a dropped UID cannot execute this local runner, if applicable.

    Returns:
        A precise unsupported-topology diagnostic, or ``None`` when paths are
        executable by the runner's isolated UIDs.
    """
    runtime_paths = (
        ("supervisor interpreter", Path(sys.executable).resolve(strict=True)),
        ("runner working directory", Path.cwd().resolve(strict=True)),
    )
    for label, runtime_path in runtime_paths:
        for component in (*reversed(runtime_path.parents), runtime_path):
            component_mode = stat.S_IMODE(component.stat().st_mode)
            if component_mode & stat.S_IXOTH:
                continue
            return (
                f"unsupported sandbox runtime topology: {label} component "
                f"{component} has mode {component_mode:04o}; validate the live "
                "runner path inside the repository Docker image"
            )
    return None
