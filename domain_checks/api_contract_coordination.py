# Copyright (c) 2026 PitchAI. All rights reserved.
"""Process-local coordination for API checks that share scarce resources."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


_COORDINATION_KEY = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")


class InvalidCoordinationKeyError(ValueError):
    """A configured API coordination key is unsafe or malformed."""

    def __init__(self) -> None:
        """Initialize a stable, secret-safe configuration failure."""
        message = "coordination_key must be a 1-80 character lowercase resource key"
        super().__init__(message)


class ApiContractCoordinator:
    """Serialize API requests that declare the same scarce-resource key."""

    def __init__(self) -> None:
        """Initialize an empty lock registry for one monitor process."""
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def request_slot(self, raw_key: str | None) -> AsyncGenerator[str | None, None]:
        """Hold a fair process-local lock when a check declares a key.

        Yields:
            The validated resource key, or ``None`` for an uncoordinated check.
        """
        key = self.normalize_key(raw_key)
        if key is None:
            yield None
            return

        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        async with lock:
            yield key

    @staticmethod
    def normalize_key(raw_key: str | None) -> str | None:
        """Validate and normalize one optional resource key.

        Returns:
            The normalized key, or ``None`` when coordination is not requested.

        Raises:
            InvalidCoordinationKeyError: The key is not a safe resource key.
        """
        if raw_key is None:
            return None
        if raw_key != raw_key.strip() or _COORDINATION_KEY.fullmatch(raw_key) is None:
            raise InvalidCoordinationKeyError
        return raw_key
