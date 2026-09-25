# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock guardian audit storage against raw authentication material."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from auth_reset_guardian.audit import AuditStore
from auth_reset_guardian.clients import SimulationSource
from auth_reset_guardian.guardian import Guardian
from domain_checks.testing import verify
from tests.auth_reset_guardian_support import UTC, guardian_fixture

if TYPE_CHECKING:
    from pathlib import Path


def test_audit_never_contains_raw_provider_ids_or_auth_material(
    tmp_path: Path,
) -> None:
    """Exclude raw provider IDs and authentication material from audit bytes."""
    now = datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
    raw_credit_id = "opaque-credit-secret-value"
    db_path = tmp_path / "audit.sqlite3"
    source = SimulationSource(
        guardian_fixture(
            expires_at=now + timedelta(hours=3),
            credit_id=raw_credit_id,
        ),
        clock=lambda: now,
    )
    with AuditStore(db_path) as audit:
        _ = Guardian(source=source, audit=audit, clock=lambda: now).run(
            mode="simulation",
            dry_run=False,
        )
    database_bytes = db_path.read_bytes()
    verify(raw_credit_id.encode() not in database_bytes)
    verify(b"access_token" not in database_bytes)
    verify(b"refresh_token" not in database_bytes)
    verify(b"Authorization" not in database_bytes)
