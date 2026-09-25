# Copyright (c) 2026 PitchAI. All rights reserved.
"""HTTP client construction at the runner infrastructure boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import AsyncClient

if TYPE_CHECKING:
    from collections.abc import Callable

    type HttpClientFactory = Callable[..., AsyncClient]

_RUNNER_USER_AGENT = "PitchAI E2E Runner"


def registry_http_client(factory: HttpClientFactory = AsyncClient) -> AsyncClient:
    """Create the bounded client used for registry claim and completion calls.

    Returns:
        A client with the runner's explicit transport identity.
    """
    headers = {"User-Agent": _RUNNER_USER_AGENT}
    return factory(headers=headers)
