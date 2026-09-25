# Copyright (c) 2026 PitchAI. All rights reserved.
"""Output-redaction variants for credentials forwarded to trusted canaries."""

from __future__ import annotations

import base64


def sensitive_output_variants(credentials: dict[str, str]) -> tuple[str, ...]:
    """Return raw and Basic-auth forms that must never enter captured output."""
    credential_values = credentials.values()
    non_empty_values = (value for value in credential_values if value)
    values = list(non_empty_values)
    username = credentials.get("AFASASK_DEMO_USERNAME", "")
    password = credentials.get("AFASASK_DEMO_PASSWORD", "")
    if username and password:
        basic_pair = f"{username}:{password}"
        basic_token = base64.b64encode(basic_pair.encode()).decode("ascii")
        values.extend((basic_pair, basic_token, f"Basic {basic_token}"))
    return tuple(dict.fromkeys(values))
