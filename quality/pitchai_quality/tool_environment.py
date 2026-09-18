# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build the deterministic process environment for locked quality tools."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def locked_tool_environment(venv: Path) -> dict[str, str]:
    """Force subprocesses to use executables bundled in the selected environment.

    Returns:
        A complete subprocess environment with locked tool paths first.

    Raises:
        FileNotFoundError: If the pinned Semgrep engine is missing.
        RuntimeError: If the process has no executable search path.
    """
    bundled_tools = venv / "lib" / "python3.12" / "site-packages" / "semgrep" / "bin"
    semgrep_core = bundled_tools / "semgrep-core"
    if not semgrep_core.is_file():
        message = f"locked Semgrep core is missing: {semgrep_core}"
        raise FileNotFoundError(message)
    environment = dict(os.environ)
    path_value = environment.get("PATH")
    if path_value is None:
        message = "PATH is required to execute the locked quality toolchain"
        raise RuntimeError(message)
    environment["PATH"] = os.pathsep.join((str(bundled_tools), str(venv / "bin"), path_value))
    environment.setdefault("SEMGREP_SEND_METRICS", "off")
    return environment
