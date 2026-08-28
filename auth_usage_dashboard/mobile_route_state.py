# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dependency state for the protected native-client routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .mobile_challenges import ChallengeStore
    from .mobile_registry import AppAttestRegistry
    from .timeseries_types import JsonObject


class CapacityServiceSurface(Protocol):
    """Capacity operations required by protected native routes."""

    async def snapshot(self) -> JsonObject:
        """Return the current capacity snapshot."""
        raise NotImplementedError

    async def request_manual_probe(self) -> JsonObject:
        """Request a bounded refresh and return its current state."""
        raise NotImplementedError


@dataclass(frozen=True)
class MobileRouteConfiguration:
    """Refresh and challenge values exposed in native responses."""

    challenge_ttl_seconds: int
    manual_refresh_min_interval_seconds: int
    background_refresh_seconds: int


@dataclass(frozen=True)
class MobileRouteDependencies:
    """Process-local services used by every native route."""

    registry: AppAttestRegistry
    challenges: ChallengeStore
    service: CapacityServiceSurface
    configuration: MobileRouteConfiguration


class MobileStateContainer(Protocol):
    """Typed view of the native route dependency slot in app state."""

    mobile_route_dependencies: MobileRouteDependencies

    def mobile_state_marker(self) -> None:
        """Identify the route state contract to static tooling."""
        raise NotImplementedError

    def mobile_dependency_marker(self) -> None:
        """Provide the paired marker required for a structural protocol."""
        raise NotImplementedError
