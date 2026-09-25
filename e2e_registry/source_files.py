# Copyright (c) 2026 PitchAI. All rights reserved.
"""Filesystem boundary for uploaded E2E sources and run artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from e2e_registry.app_policy import safe_filename

if TYPE_CHECKING:
    from e2e_registry.models import DatabaseRecord
    from e2e_registry.settings import RegistrySettings

_SOURCE_PREVIEW_LIMIT = 80_000


class SourceFileError(ValueError):
    """Raised when a source or artifact path violates the storage contract."""


class StoredSource(NamedTuple):
    """Metadata for one immutable uploaded source snapshot."""

    relative_path: str
    filename: str
    sha256: str


def validated_source_filename(kind: str, supplied_name: str) -> str:
    """Return a safe source filename with the extension required by its kind.

    Raises:
        SourceFileError: If the filename extension does not match the test kind.
    """
    default_filename = "test.py" if kind == "playwright_python" else "test.js"
    filename = safe_filename(supplied_name, default=default_filename)
    if kind == "playwright_python" and not filename.endswith(".py"):
        message = "python_test_must_be_.py"
        raise SourceFileError(message)
    if kind == "puppeteer_js" and not filename.endswith((".js", ".mjs")):
        message = "puppeteer_test_must_be_.js"
        raise SourceFileError(message)
    return filename


def store_source(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    filename: str,
    content: bytes,
) -> StoredSource:
    """Persist one source file below the configured tests directory.

    Returns:
        Metadata for the immutable source snapshot.
    """
    relative_path = Path(tenant_id) / test_id / filename
    destination = confined_path(settings.tests_dir, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    source_digest = hashlib.sha256(content).hexdigest()
    return StoredSource(str(relative_path), filename, source_digest)


def remove_replaced_source(
    settings: RegistrySettings,
    *,
    old_relative_path: str,
    new_relative_path: str,
) -> None:
    """Delete a superseded source after validating its persisted path.

    Raises:
        SourceFileError: If the persisted source path is not a regular file.
    """
    if not old_relative_path or old_relative_path == new_relative_path:
        return
    old_path = confined_path(settings.tests_dir, Path(old_relative_path))
    if old_path.exists():
        if not old_path.is_file():
            message = "stored source path is not a file"
            raise SourceFileError(message)
        old_path.unlink()


def read_source_preview(settings: RegistrySettings, test: DatabaseRecord) -> tuple[str | None, str | None]:
    """Read a bounded source preview for the tenant UI.

    Returns:
        The source filename and text, or two ``None`` values when unavailable.
    """
    source_relative_path = str(test.get("source_relpath") or "").strip()
    if not source_relative_path:
        return None, None
    source_path = confined_path(settings.tests_dir, Path(source_relative_path))
    if not source_path.exists() or not source_path.is_file():
        return None, None
    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    if len(source_text) > _SOURCE_PREVIEW_LIMIT:
        source_text = source_text[:_SOURCE_PREVIEW_LIMIT] + "\n...truncated..."
    return source_path.name, source_text


def source_download_path(settings: RegistrySettings, test: DatabaseRecord) -> Path:
    """Resolve an existing code-test source for download.

    Returns:
        The validated source path.

    Raises:
        SourceFileError: If the source path is absent or invalid.
    """
    relative_path = str(test.get("source_relpath") or "").strip()
    if not relative_path:
        message = "source_missing"
        raise SourceFileError(message)
    source_path = confined_path(settings.tests_dir, Path(relative_path))
    if not source_path.exists() or not source_path.is_file():
        message = "source_not_found"
        raise SourceFileError(message)
    return source_path


def definition_download_path(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    definition_json: str,
) -> Path:
    """Materialize the stored StepFlow definition for download.

    Returns:
        The materialized definition path.
    """
    relative_path = Path(tenant_id) / test_id / "definition.json"
    destination = confined_path(settings.tests_dir, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(definition_json, encoding="utf-8", errors="replace")
    return destination


def artifact_download_path(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    run_id: str,
    artifact_name: str,
) -> Path:
    """Resolve an existing run artifact below the configured artifact root.

    Returns:
        The validated artifact path.

    Raises:
        SourceFileError: If the artifact does not exist as a regular file.
    """
    relative_path = Path(tenant_id) / test_id / run_id / artifact_name
    artifact_path = confined_path(settings.artifacts_dir, relative_path)
    if not artifact_path.exists() or not artifact_path.is_file():
        message = "artifact_not_found"
        raise SourceFileError(message)
    return artifact_path


def confined_path(base_directory: str, relative_path: Path) -> Path:
    """Resolve a child path and reject traversal outside its configured root.

    Returns:
        The resolved child path.

    Raises:
        SourceFileError: If the child escapes the configured root.
    """
    base = Path(base_directory).resolve()
    candidate = (base / relative_path).resolve()
    if base not in candidate.parents:
        message = "invalid_storage_path"
        raise SourceFileError(message)
    return candidate
