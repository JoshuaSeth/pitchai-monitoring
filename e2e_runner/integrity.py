# Copyright (c) 2026 PitchAI. All rights reserved.
"""Claimed-source integrity enforcement for submitted code tests."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from e2e_runner.storage import (
    ArtifactStorageError,
    prepare_staging_directory,
    validate_no_symlink_path,
    validate_prepared_run_directory,
    write_new_private_file,
)

if TYPE_CHECKING:
    from pathlib import Path

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TESTS_DIRECTORY_NOT_FOUND = "tests_directory_not_found"
_SOURCE_NOT_FOUND = "source_not_found"
_INVALID_SOURCE_PATH = "invalid_source_path"
_MISSING_SOURCE_HASH = "missing_source_hash"
_INVALID_SOURCE_HASH = "invalid_source_hash"
_SOURCE_READ_FAILED = "source_read_failed"
_SOURCE_HASH_MISMATCH = "source_hash_mismatch"
_SOURCE_STAGING_FAILED = "source_staging_failed"


@dataclass(frozen=True)
class SourceIntegrityFailure:
    """Expected source-boundary failure represented without exception control flow."""

    error_kind: str
    error_message: str


@dataclass(frozen=True)
class VerifiedSource:
    """Original verified source identity and its private execution snapshot."""

    original_path: Path
    staged_path: Path
    sha256: str


@dataclass(frozen=True)
class VerifiedSourceBytes:
    """Claimed source bytes after digest verification."""

    content: bytes
    sha256: str


type SourcePathResult = Path | SourceIntegrityFailure
type SourceBytesResult = SourceIntegrityFailure | VerifiedSourceBytes
type SourceStageResult = SourceIntegrityFailure | VerifiedSource
type StagedPathResult = Path | SourceIntegrityFailure


def _resolve_claimed_source(tests_dir: Path, source_relpath: str) -> SourcePathResult:
    try:
        validate_no_symlink_path(tests_dir / source_relpath)
    except ArtifactStorageError:
        return SourceIntegrityFailure(_INVALID_SOURCE_PATH, "claimed source path contains a symbolic link")
    try:
        base_directory = tests_dir.resolve(strict=True)
    except OSError:
        return SourceIntegrityFailure(
            _TESTS_DIRECTORY_NOT_FOUND,
            f"tests directory is unavailable: {tests_dir}",
        )
    try:
        source_path = (base_directory / source_relpath).resolve(strict=True)
    except OSError:
        return SourceIntegrityFailure(
            _SOURCE_NOT_FOUND,
            f"claimed source file is unavailable: {source_relpath}",
        )
    if base_directory not in source_path.parents:
        return SourceIntegrityFailure(_INVALID_SOURCE_PATH, "source_relpath resolves outside tests_dir")
    if not source_path.is_file():
        return SourceIntegrityFailure(_SOURCE_NOT_FOUND, f"claimed source is not a file: {source_relpath}")
    return source_path


def _read_verified_source(
    source_path: Path,
    *,
    source_relpath: str,
    expected_sha256: str,
) -> SourceBytesResult:
    try:
        source_bytes = source_path.read_bytes()
    except OSError:
        return SourceIntegrityFailure(_SOURCE_READ_FAILED, f"could not read claimed source: {source_relpath}")
    actual_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        return SourceIntegrityFailure(
            _SOURCE_HASH_MISMATCH,
            f"claimed source digest mismatch for {source_relpath}",
        )
    return VerifiedSourceBytes(content=source_bytes, sha256=actual_sha256)


def _stage_source_bytes(
    *,
    source_path: Path,
    source_relpath: str,
    source_bytes: bytes,
    staging_dir: Path,
    prepared_staging_directory: bool,
) -> StagedPathResult:
    staged_path = staging_dir / f"verified_source{source_path.suffix}"
    directory_action = validate_prepared_run_directory if prepared_staging_directory else prepare_staging_directory
    try:
        directory_action(staging_dir)
    except (ArtifactStorageError, OSError):
        return SourceIntegrityFailure(
            _SOURCE_STAGING_FAILED,
            f"could not prepare source staging directory: {staging_dir}",
        )
    try:
        write_new_private_file(staged_path, source_bytes)
    except (ArtifactStorageError, OSError):
        return SourceIntegrityFailure(_SOURCE_STAGING_FAILED, f"could not stage verified source: {source_relpath}")
    return staged_path


async def stage_verified_source(
    *,
    tests_dir: Path,
    source_relpath: str,
    expected_sha256: str | None,
    staging_dir: Path,
    prepared_staging_directory: bool = False,
) -> SourceStageResult:
    """Verify claimed bytes and stage that exact immutable snapshot for execution.

    Returns:
        A verified source snapshot or a stable expected boundary failure.
    """
    if expected_sha256 is None:
        return SourceIntegrityFailure(_MISSING_SOURCE_HASH, "source_sha256 is required for code tests")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        return SourceIntegrityFailure(
            _INVALID_SOURCE_HASH,
            "source_sha256 must be a lowercase SHA-256 digest",
        )

    source_outcome = await asyncio.to_thread(
        _resolve_claimed_source,
        tests_dir,
        source_relpath,
    )
    if isinstance(source_outcome, SourceIntegrityFailure):
        return source_outcome
    source_path = source_outcome

    bytes_outcome = await asyncio.to_thread(
        _read_verified_source,
        source_path,
        source_relpath=source_relpath,
        expected_sha256=expected_sha256,
    )
    if isinstance(bytes_outcome, SourceIntegrityFailure):
        return bytes_outcome

    staged_outcome = await asyncio.to_thread(
        _stage_source_bytes,
        source_path=source_path,
        source_relpath=source_relpath,
        source_bytes=bytes_outcome.content,
        staging_dir=staging_dir,
        prepared_staging_directory=prepared_staging_directory,
    )
    if isinstance(staged_outcome, SourceIntegrityFailure):
        return staged_outcome
    return VerifiedSource(
        original_path=source_path,
        staged_path=staged_outcome,
        sha256=bytes_outcome.sha256,
    )
