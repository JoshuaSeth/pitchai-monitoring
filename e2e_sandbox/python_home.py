# Copyright (c) 2026 PitchAI. All rights reserved.
"""Supply an owned temporary home only to standalone invocations missing HOME."""

from __future__ import annotations

import os
from contextlib import ExitStack
from tempfile import TemporaryDirectory


def invocation_home() -> ExitStack:
    """Preserve configured HOME; remove only the fallback allocated here.

    Returns:
        Cleanup for only the environment entry and directory allocated here.
    """
    if "HOME" in os.environ:
        return ExitStack()
    with ExitStack() as cleanup:
        directory = cleanup.enter_context(TemporaryDirectory(prefix="pitchai-sandbox-home-"))
        os.environ["HOME"] = directory
        cleanup.callback(os.environ.pop, "HOME", None)
        return cleanup.pop_all()
