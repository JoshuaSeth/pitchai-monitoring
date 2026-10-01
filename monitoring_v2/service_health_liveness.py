# Copyright (c) 2026 PitchAI. All rights reserved.
"""Explicit container-local liveness gateway for the monitoring health probe."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Final

from httpx import Client

_TIMEOUT_SECONDS: Final = 5.0


@dataclass(frozen=True)
class LivenessReceipt:
    """Status and body retained from one container-local liveness request.

    Attributes:
        status_code: HTTP status the local liveness route returned.
        text: Response body, decoded by the role that owns the route.
    """

    status_code: int
    text: str


def fetch_liveness(url: str, *, timeout_seconds: float = _TIMEOUT_SECONDS) -> LivenessReceipt:
    """Return the receipt of one bounded request to a container-local route.

    An unreachable loopback route propagates its transport failure unchanged, so
    the caller's boundary classification names the failure instead of this
    gateway flattening it.

    Args:
        url: Loopback liveness endpoint owned by the probed service.
        timeout_seconds: Bounded timeout for the liveness request.

    Returns:
        The status and body of the local liveness response.
    """
    client_factory = partial(Client, timeout=timeout_seconds)
    with client_factory() as client:
        response = client.get(url)
    return LivenessReceipt(status_code=response.status_code, text=response.text)
