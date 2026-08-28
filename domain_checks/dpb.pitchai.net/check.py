# Copyright (c) 2026 PitchAI. All rights reserved.
"""Production monitoring configuration for dpb.pitchai.net."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import cast

_CANONICAL_CHECK_PATH = Path(__file__).parents[1] / "deplanbook.com" / "check.py"
_INVALID_CHECK_ERROR = "canonical DePlanBook plugin did not define a CHECK mapping"

_module_variables = cast("dict[str, object]", runpy.run_path(str(_CANONICAL_CHECK_PATH)))
_canonical_check = _module_variables.get("CHECK")
if not isinstance(_canonical_check, dict):
    raise TypeError(_INVALID_CHECK_ERROR)

CHECK = cast("dict[str, object]", _canonical_check.copy())
CHECK.update(
    {
        "domain": "dpb.pitchai.net",
        "url": "https://dpb.pitchai.net",
        "expected_final_host_suffix": "deplanbook.com",
    },
)
