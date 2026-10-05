# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry source naming, confined filesystem operations and StepFlow decoding."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast

from fastapi import HTTPException

from .app_inputs import safe_filename
from .stepflow import parse_definition_bytes, validate_definition

if TYPE_CHECKING:
    from types import TracebackType

    from .dashboard_records import Record


@dataclass
class UiUploadFailure:
    """Retain ordinary file/DB failure text for the existing UI response, never cancellation."""

    error: Exception | None = None

    def __enter__(self) -> Self:
        """Begin the caller's single IO operation without changing pending metadata.

        Returns:
            This operation's failure record.
        """
        return self

    def __exit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                 _traceback: TracebackType | None) -> bool:
        """Keep the error object for rendering while allowing non-ordinary exits to propagate.

        Returns:
            True only when the UI must render an ordinary operation failure.
        """
        if isinstance(error, Exception):
            self.error = error
            return True
        return False


def parse_upload_definition(raw: bytes, content_type: str | None) -> Record:
    """Decode and validate the uploaded definition in the original order.

    Returns:
        The normalized StepFlow definition.
    """
    return cast("Record", validate_definition(parse_definition_bytes(raw, content_type=content_type)))


def code_filename(kind: str, uploaded_name: str | None) -> str:
    """Choose the original default and sanitize a code-upload filename.

    Returns:
        The filename, before the caller's extension check.
    """
    default = "test.py" if kind == "playwright_python" else "test.js"
    return safe_filename(uploaded_name or "", default=default)


def extension_error(kind: str, filename: str) -> str | None:
    """Keep Python and Puppeteer extension refusal separate from file IO.

    Returns:
        The existing API/upload error code, or None for an accepted suffix.
    """
    if kind == "playwright_python" and not filename.endswith(".py"):
        return "python_test_must_be_.py"
    if kind == "puppeteer_js" and not filename.endswith((".js", ".mjs")):
        return "puppeteer_test_must_be_.js"
    return None


def sha256_hex(raw: bytes) -> str:
    """Hash the actual uploaded bytes for the existing source identity.

    Returns:
        The lowercase SHA-256 digest.
    """
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SourceLocation:
    """Preserve the unresolved relative spelling and resolved confinement boundary."""

    base: Path
    relative: Path
    resolved: Path

    @classmethod
    def for_test(cls, directory: str, tenant_id: str, test_id: str, filename: str) -> SourceLocation:
        """Resolve an upload beneath its original tenant/test hierarchy.

        Returns:
            The candidate path without writing or admitting it.
        """
        base = Path(directory).resolve()
        relative = Path(tenant_id) / test_id / filename
        return cls(base, relative, (base / relative).resolve())

    @property
    def contained(self) -> bool:
        """Report the original strict ancestor check.

        Returns:
            Whether the resolved file is below the resolved source root.
        """
        return self.base in self.resolved.parents

    def write(self, raw: bytes) -> None:
        """Create the admitted file's parent and write its complete bytes."""
        self.resolved.parent.mkdir(parents=True, exist_ok=True)
        self.resolved.write_bytes(raw)

    def remove_previous(self, previous_relative: str) -> None:
        """Remove only a changed, confined old regular file; let the UI/API edge handle IO failure."""
        if previous_relative and previous_relative != str(self.relative):
            old_file = (self.base / previous_relative).resolve()
            if self.base in old_file.parents and old_file.exists() and old_file.is_file():
                old_file.unlink(missing_ok=True)


def downloadable_source(directory: str, tenant_id: str, test_id: str, test: Record) -> Path:
    """Resolve source or materialize the existing StepFlow download.

    Returns:
        A confined source path.

    Raises:
        HTTPException: The original route's missing/confinement predicate fails.
    """
    kind = str(test.get("test_kind") or "stepflow").strip().lower() or "stepflow"
    if kind == "stepflow":
        text = str(test.get("definition_json") or "").strip() or "{}"
        location = SourceLocation.for_test(directory, tenant_id, test_id, "definition.json")
        if not location.contained:
            raise HTTPException(status_code=400, detail="invalid_path")
        location.resolved.parent.mkdir(parents=True, exist_ok=True)
        location.resolved.write_text(text, encoding="utf-8", errors="replace")
        return location.resolved
    relative = str(test.get("source_relpath") or "").strip()
    if not relative:
        raise HTTPException(status_code=404, detail="source_missing")
    base = Path(directory).resolve()
    path = (base / relative).resolve()
    if base not in path.parents:
        raise HTTPException(status_code=400, detail="invalid_path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="source_not_found")
    return path
