# Copyright (c) 2026 PitchAI. All rights reserved.
"""Upload page rendering and the UI's code-file preparation boundary."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from e2e_registry.app_source_files import SourceLocation, UiUploadFailure, code_filename, extension_error, sha256_hex

if TYPE_CHECKING:
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    from .app_context import RegistryContext
    from .app_upload_values import UploadedTest


@dataclass(frozen=True)
class UploadPage:
    """The current request's renderer and source root, without global request state."""

    context: RegistryContext
    request: Request

    def render(self, *, error: str | None = None, message: str | None = None) -> HTMLResponse:
        """Render the existing template fields.

        Returns:
            The form response with its original status and template context.
        """
        return self.context.templates.TemplateResponse(
            "upload.html", {"request": self.request, "error": error, "msg": message},
        )

    def prepare_code(self, source: UploadedTest, raw: bytes, *, tenant_id: str, kind: str) -> str | None:
        """Validate/write a new code file and populate metadata only after a successful write.

        Returns:
            The existing form error text, or None when code metadata is ready for insertion.
        """
        source.source_filename = code_filename(kind, source.source_filename)
        if error := extension_error(kind, source.source_filename):
            return error
        source.name = source.name or source.source_filename
        test_id = str(uuid.uuid4())
        location = SourceLocation.for_test(self.context.settings.tests_dir, tenant_id, test_id, source.source_filename)
        if not location.contained:
            return "invalid_upload_path"
        with UiUploadFailure() as write:
            location.write(raw)
        if write.error is not None:
            return f"write_failed: {write.error}"
        source.source_relpath = str(location.relative)
        source.source_sha = sha256_hex(raw)
        source.test_id = test_id
        return None
