# Copyright (c) 2026 PitchAI. All rights reserved.
"""CLI binding for the organization-exhaustion guardian release."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import cli as legacy_cli
from .organization_guardian import OrganizationGuardian
from .organization_io import SingleAttemptBrokerProviderSource

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Bind the current policy and delegate argument/lock handling to the stable CLI.

    Returns:
        The stable CLI exit status.
    """
    guardian_binding = "Guardian"
    provider_binding = "BrokerProviderSource"
    setattr(legacy_cli, guardian_binding, OrganizationGuardian)
    setattr(legacy_cli, provider_binding, SingleAttemptBrokerProviderSource)
    return legacy_cli.main(list(argv) if argv is not None else None)


if __name__ == "__main__":
    raise SystemExit(main())
