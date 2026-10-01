# Copyright (c) 2026 PitchAI. All rights reserved.
"""Wake hints cannot erase signals published during an evaluation."""

from __future__ import annotations

import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from .cli import main
from .organization_guardian import OrganizationGuardian
from .organization_runtime import OrganizationInventory
from .proof_wake import consume_proof_wake
from .test_organization_assertions import require_equal

if TYPE_CHECKING:
    from collections.abc import Generator

    from .organization_runtime import OrganizationRunContext


@contextmanager
def expect_error(error_type: type[Exception]) -> Generator[None]:
    """Require a specific failure without an optional test-runner dependency.

    Yields:
        Control to the operation expected to fail.

    Raises:
        AssertionError: The operation did not raise the expected exception.
    """
    try:
        yield
    except error_type:
        return
    message = f"expected {error_type.__name__}"
    raise AssertionError(message)


class TestProofWake:
    """Check both sides of atomic publication versus hint consumption."""

    @staticmethod
    def test_new_signal_after_consumption_survives() -> None:
        """A hint arriving during the subsequent refresh remains pending."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": str(path)}):
                path.write_text("old hint", encoding="utf-8")
                consume_proof_wake()
                replacement = path.with_suffix(".new")
                replacement.write_text("new hint", encoding="utf-8")
                replacement.replace(path)
                require_equal(path.read_text(encoding="utf-8"), "new hint")
                consume_proof_wake()
                require_equal(path.exists(), expected=False)

    @staticmethod
    def test_replacement_before_consumption_coalesces() -> None:
        """All proofs are reread after consuming the latest pre-run signal."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            with patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": str(path)}):
                path.write_text("first", encoding="utf-8")
                replacement = path.with_suffix(".new")
                replacement.write_text("second", encoding="utf-8")
                replacement.replace(path)
                consume_proof_wake()
                require_equal(path.exists(), expected=False)
                consume_proof_wake()

    @staticmethod
    def test_disabled_consumer_leaves_files_alone() -> None:
        """An unconfigured invocation does not consume any production signal."""
        with patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": ""}):
            consume_proof_wake()

    @staticmethod
    def test_source_setup_failure_preserves_pending_hint() -> None:
        """An evaluation that cannot initialize leaves the signal for retry."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            path.write_text("pending", encoding="utf-8")
            database = Path(temporary) / "audit.sqlite3"
            with (
                patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": str(path)}),
                patch("auth_reset_guardian.cli._live_source", side_effect=RuntimeError("source unavailable")),
                expect_error(RuntimeError),
            ):
                main(["--audit-db", str(database), "run", "--no-notify"])
            require_equal(path.read_text(encoding="utf-8"), "pending")

    @staticmethod
    def test_simulation_preserves_pending_live_hint() -> None:
        """Offline validation cannot acknowledge an actual provider signal."""
        fixture = Path(__file__).resolve().parents[1] / "fixtures/auth-reset-guardian-expiring.json"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            path.write_text("pending", encoding="utf-8")
            database = Path(temporary) / "audit.sqlite3"
            with patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": str(path)}):
                result = main([
                    "--audit-db", str(database), "run", "--simulate", str(fixture),
                    "--now", "2026-08-11T19:30:00Z", "--dry-run", "--no-notify",
                ])
            require_equal(result, 0)
            require_equal(path.read_text(encoding="utf-8"), "pending")

    @staticmethod
    def test_live_entry_point_consumes_only_under_lock() -> None:
        """Check both live and dry-run modes through the installed CLI contract."""
        for dry_run in (False, True):
            TestProofWake.check_live_entry_point(dry_run=dry_run)

    @staticmethod
    def check_live_entry_point(*, dry_run: bool) -> None:
        """A mocked evaluation checks lock ownership and publishes the next hint."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pending.json"
            path.write_text("first", encoding="utf-8")
            database = Path(temporary) / "audit.sqlite3"

            def evaluate(context: OrganizationRunContext, *, phase: str) -> OrganizationInventory:
                require_equal(phase, "initial_inventory")
                require_equal(context.audit.path, database)
                require_equal(path.exists(), dry_run)
                with (
                    database.with_suffix(".sqlite3.lock").open("rb") as stream,
                    expect_error(BlockingIOError),
                ):
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                path.write_text("next", encoding="utf-8")
                return OrganizationInventory(descriptors=(), observations={}, failed_account_refs=set())

            arguments = ["--audit-db", str(database), "run", "--no-notify"]
            if dry_run:
                arguments.append("--dry-run")
            with (
                patch.dict(os.environ, {"AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH": str(path)}),
                patch("auth_reset_guardian.cli._live_source"),
                patch("auth_reset_guardian.cli.Guardian", OrganizationGuardian),
                patch("auth_reset_guardian.organization_guardian.refresh_organization", side_effect=evaluate),
            ):
                require_equal(main(arguments), 0)
            require_equal(path.read_text(encoding="utf-8"), "next")
