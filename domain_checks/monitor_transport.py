# Copyright (c) 2026 PitchAI. All rights reserved.
"""The native HTTP transport used by one monitoring loop."""

from httpx import AsyncClient


class MonitorHttpClient(AsyncClient):
    """Own the existing monitor user agent and inherited HTTPX context lifecycle."""

    def __init__(self) -> None:
        """Create the original client without opening connections or changing HTTPX defaults."""
        super().__init__(headers={"User-Agent": "PitchAI Service Monitoring Bot"})
