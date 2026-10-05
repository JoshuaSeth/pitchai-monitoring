# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native registry alert transport, owned after the completion transaction."""

from httpx import AsyncClient


class RegistryHttpClient(AsyncClient):
    """Retain HTTPX defaults and the registry's existing user agent/lifecycle."""

    def __init__(self) -> None:
        """Construct the original client without opening a connection."""
        super().__init__(headers={"User-Agent": "PitchAI E2E Registry"})
