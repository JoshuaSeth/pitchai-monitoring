# Copyright (c) 2026 PitchAI. All rights reserved.
"""Private-file admission and unrelated-database preservation in isolation."""

from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from .dft_journal import DftJournal
from .dft_retention_consumer import CheckerObservation
from .dft_test_support import require, require_error

_PRIVATE_FILE = 0o600


class TestJournalStorage(unittest.TestCase):
    """Use only newly allocated temporary directories and synthetic databases."""

    @staticmethod
    def test_foreign_database_is_not_adopted() -> None:
        """Opening an unrelated private SQLite file must not add any table."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unrelated.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.commit()
            connection.close()
            path.chmod(_PRIVATE_FILE)
            original = path.read_bytes()
            with require_error(ValueError, "dft_journal_identity_mismatch"):
                DftJournal(path).close()
            require(condition=path.read_bytes() == original, message="foreign database changed during refusal")

    @staticmethod
    def test_created_private_journal_reopens_with_original_intent() -> None:
        """New state is private and retains the same incident and retry bytes."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "consumer.sqlite"
            first = DftJournal(path)
            first.record(CheckerObservation(errors=("checker_unavailable",)), now=1)
            pending = first.pending(now=1)
            first.close()
            require(condition=stat.S_IMODE(path.stat().st_mode) == _PRIVATE_FILE,
                    message="new consumer metadata is not private")
            restored = DftJournal(path)
            require(condition=pending is not None and restored.pending(now=1) == pending,
                    message="private journal restart changed retained transition")
            restored.close()

    @staticmethod
    def test_prior_schema_is_not_implicitly_migrated() -> None:
        """A prior source journal stays byte-identical when selection history is absent."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prior.sqlite"
            prior = DftJournal(path)
            prior.connection.execute("DROP TABLE source_selections")
            prior.connection.execute("PRAGMA user_version=1")
            prior.connection.commit()
            prior.close()
            original = path.read_bytes()
            with require_error(ValueError, "dft_journal_identity_mismatch"):
                DftJournal(path).close()
            require(condition=path.read_bytes() == original, message="old journal was modified or silently migrated")

    @staticmethod
    def test_untrusted_paths_are_refused_without_repair() -> None:
        """No chmod, adoption or writes occur through unsafe aliases or modes."""
        for mutation in ("file_mode", "parent_mode", "symlink", "hardlink", "parent_alias"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                private = root / "private"
                private.mkdir(mode=0o700)
                path = private / "consumer.sqlite"
                DftJournal(path).close()
                original = path.read_bytes()
                candidate = path
                if mutation == "file_mode":
                    path.chmod(0o644)
                elif mutation == "parent_mode":
                    private.chmod(0o755)
                elif mutation == "parent_alias":
                    alias = root / "alias"
                    alias.symlink_to(private, target_is_directory=True)
                    candidate = alias / path.name
                else:
                    candidate = private / "alias.sqlite"
                    if mutation == "symlink":
                        candidate.symlink_to(path)
                    else:
                        os.link(path, candidate)
                prior_mode = stat.S_IMODE(path.stat().st_mode)
                with require_error(ValueError, "dft_journal_unsafe"):
                    DftJournal(candidate).close()
                require(condition=path.read_bytes() == original and stat.S_IMODE(path.stat().st_mode) == prior_mode,
                        message="unsafe journal refusal changed existing data or permissions")
