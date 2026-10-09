# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed multipart fields, pending source metadata and UI failure translation."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

import fastapi

if TYPE_CHECKING:
    from .dashboard_records import Record


@dataclass
class UploadForm:
    """The UI's existing independent form fields and defaults, without new constraints."""

    name: Annotated[str, fastapi.Form()] = ""
    base_url: Annotated[str, fastapi.Form()] = ""
    kind: Annotated[str, fastapi.Form()] = "stepflow"
    interval_seconds: Annotated[int, fastapi.Form()] = 300


@dataclass
class ApiUploadForm(UploadForm):
    """API-specific defaults and scheduling/alert fields, bound by native FastAPI."""

    kind: Annotated[str, fastapi.Form()] = ""
    timeout_seconds: Annotated[int, fastapi.Form()] = 45
    jitter_seconds: Annotated[int, fastapi.Form()] = 30
    down_after_failures: Annotated[int, fastapi.Form()] = 2
    up_after_successes: Annotated[int, fastapi.Form()] = 2
    notify_on_recovery: Annotated[str, fastapi.Form()] = "0"
    dispatch_on_failure: Annotated[str, fastapi.Form()] = "0"


@dataclass
class UploadedTest:
    """Pending metadata shared by the definition and code-file insertion branches."""

    name: str
    definition: "Record | None" = None
    source_relpath: str | None = None
    source_filename: str | None = None
    source_sha: str | None = None
    test_id: str | None = None
    content_type: str | None = None
