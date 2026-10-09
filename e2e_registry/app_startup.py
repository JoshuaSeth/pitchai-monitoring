# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry startup IO with unchanged schema, directory and quarantine boundaries."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self

from . import db as dbm
from .app_host_policy import RegistryHostPolicy

if TYPE_CHECKING:
    from types import TracebackType

    from .app_context import RegistryContext

LOGGER = logging.getLogger("e2e-registry")


@dataclass(frozen=True)
class RegistryStartup:
    """Own startup and its original logged quarantine failure boundary."""

    context: RegistryContext

    def __enter__(self) -> Self:
        """Enter only the quarantine operation's best-effort boundary.

        Returns:
            This startup context.
        """
        return self

    def __exit__(
        self, _kind: type[BaseException] | None, error: BaseException | None, _traceback: TracebackType | None,
    ) -> bool:
        """Log ordinary quarantine failure while preserving cancellation and fatal errors.

        Returns:
            Whether the original ordinary exception is handled.
        """
        if isinstance(error, Exception):
            LOGGER.error("Failed to quarantine disallowed e2e tests", exc_info=(type(error), error, _traceback))
            return True
        return False

    def run(self) -> None:
        """Run schema admission first, then best-effort directories and quarantine."""
        dbm.ensure_schema(self.context.settings)
        # These two independent directory attempts have always been best-effort.
        with suppress(Exception):
            Path(self.context.settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
        with suppress(Exception):
            Path(self.context.settings.tests_dir).mkdir(parents=True, exist_ok=True)
        with self:
            quarantined = RegistryHostPolicy(self.context).quarantine_disallowed_tests()
            if quarantined > 0:
                LOGGER.warning("Quarantined disallowed e2e tests count=%s", quarantined)
