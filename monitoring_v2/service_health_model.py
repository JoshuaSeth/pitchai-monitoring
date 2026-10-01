# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared result model for the role-aware monitoring service health contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

STATUS_HEALTHY: Final = "healthy"
STATUS_STARTING: Final = "starting"
STATUS_DEGRADED: Final = "degraded"
STATUS_UNHEALTHY: Final = "unhealthy"

EXIT_HEALTHY: Final = 0
EXIT_UNHEALTHY: Final = 1

# A degraded worker keeps making bounded progress while a dependency or a
# monitored customer system is failing. Restarting it cannot repair that
# condition, so only ``unhealthy`` asks for a restart.
_RESTARTING_STATUS: Final = STATUS_UNHEALTHY
_DETAIL_LIMIT: Final = 32


@dataclass(frozen=True)
class HealthReport:
    """One evaluated health contract result.

    Attributes:
        role: Service role the contract was evaluated for.
        service: Deployed container or unit the role belongs to.
        status: ``healthy``, ``starting``, ``degraded`` or ``unhealthy``.
        reason: Short, non-secret, operator-actionable reason code.
        detail: Additional non-secret evidence fields.
    """

    role: str
    service: str
    status: str
    reason: str
    detail: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        """Return the process exit code that represents this report."""
        if self.status == _RESTARTING_STATUS:
            return EXIT_UNHEALTHY
        return EXIT_HEALTHY

    @property
    def restart_required(self) -> bool:
        """Return whether this report asks an operator or supervisor to restart."""
        return self.status == _RESTARTING_STATUS

    def render(self) -> str:
        """Return the single-line, non-secret operator rendering of the report."""
        parts = [
            f"status={self.status}",
            f"role={self.role}",
            f"service={self.service}",
            f"reason={self.reason}",
            *self.detail,
        ]
        return " ".join(parts[:_DETAIL_LIMIT])
