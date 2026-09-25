# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant browser workflow for uploading new registry tests."""

import asyncio
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from e2e_registry import db as dbm
from e2e_registry.app_context import RegistryAppContext, context_from_request
from e2e_registry.app_policy import normalize_test_kind
from e2e_registry.models import JsonObject
from e2e_registry.source_files import SourceFileError, store_source, validated_source_filename
from e2e_registry.stepflow import StepFlowValidationError, parse_definition_bytes, validate_definition

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, Response, UploadFile, JsonObject, RegistryAppContext)


@dataclass(frozen=True)
class _UiUploadForm:
    name: str = ""
    base_url: str = ""
    kind: str = "stepflow"
    interval_seconds: int = 300


@dataclass(frozen=True)
class _UiPreparedTest:
    name: str
    test_id: str | None = None
    definition: JsonObject | None = None
    source_relative_path: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None


def _ui_upload_form(
    name: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "stepflow",
    interval_seconds: Annotated[int, Form()] = 300,
) -> _UiUploadForm:
    fields = (name, base_url, kind, interval_seconds)
    return _UiUploadForm(*fields)


@router.get("/ui/upload", response_class=HTMLResponse)
async def _ui_upload(request: Request) -> Response:
    context = context_from_request(request)
    authenticated = await context.ui_auth(request)
    if authenticated is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    return context.templates.TemplateResponse(
        request,
        "upload.html",
        {"error": None, "msg": None},
    )


@router.post("/ui/upload", response_class=HTMLResponse)
async def _ui_upload_post(
    request: Request,
    file: Annotated[UploadFile, File()],
    form: Annotated[_UiUploadForm, Depends(_ui_upload_form)],
) -> Response:
    context = context_from_request(request)
    authenticated = await context.ui_auth(request)
    if authenticated is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    error: str | None = None
    message: str | None = None
    try:
        message = await _persist_ui_upload(
            context=context,
            tenant_id=authenticated.tenant_id,
            file=file,
            form=form,
        )
    except HTTPException as exc:
        error = str(exc.detail)
    except sqlite3.Error as exc:
        error = f"db_error: {exc}"
    except (OSError, SourceFileError, StepFlowValidationError) as exc:
        error = str(exc)
    return upload_response(request, error=error, message=message)


async def _persist_ui_upload(
    *,
    context: RegistryAppContext,
    tenant_id: str,
    file: UploadFile,
    form: _UiUploadForm,
) -> str:
    content = await file.read()
    normalized_kind = normalize_test_kind(form.kind)
    if not normalized_kind:
        raise HTTPException(status_code=400, detail="invalid_kind")
    if context.settings.max_upload_bytes > 0 and len(content) > context.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file_too_large")
    validated_url = context.base_url_policy.validate(form.base_url)
    prepared = _prepare_ui_test(
        context=context,
        test_identity=(tenant_id, normalized_kind),
        file=file,
        form=form,
        content=content,
    )
    created = await asyncio.to_thread(
        dbm.insert_test,
        context.settings,
        dbm.NewTest(
            tenant_id=tenant_id,
            name=prepared.name,
            base_url=validated_url,
            test_kind=normalized_kind,
            definition=prepared.definition,
            source_relpath=prepared.source_relative_path,
            source_filename=prepared.source_filename,
            source_sha256=prepared.source_sha256,
            source_content_type=file.content_type,
            test_id=prepared.test_id,
            interval_seconds=form.interval_seconds,
            timeout_seconds=45,
            jitter_seconds=30,
            down_after_failures=2,
            up_after_successes=2,
            notify_on_recovery=False,
            dispatch_on_failure=False,
        ),
    )
    return f"Created test {created.get('id') or ''}"


def _prepare_ui_test(
    *,
    context: RegistryAppContext,
    test_identity: tuple[str, str],
    file: UploadFile,
    form: _UiUploadForm,
    content: bytes,
) -> _UiPreparedTest:
    tenant_id, normalized_kind = test_identity
    if normalized_kind == "stepflow":
        raw_definition = parse_definition_bytes(content, content_type=file.content_type)
        definition = validate_definition(raw_definition)
        test_name = form.name.strip() or str(definition.get("name") or "test")
        return _UiPreparedTest(name=test_name, definition=definition)
    source_filename = validated_source_filename(normalized_kind, file.filename or "")
    test_id = str(uuid.uuid4())
    stored = store_source(
        context.settings,
        tenant_id=tenant_id,
        test_id=test_id,
        filename=source_filename,
        content=content,
    )
    return _UiPreparedTest(
        name=form.name.strip() or source_filename,
        test_id=test_id,
        source_relative_path=stored.relative_path,
        source_filename=stored.filename,
        source_sha256=stored.sha256,
    )


def upload_response(
    request: Request,
    *,
    error: str | None = None,
    message: str | None = None,
) -> Response:
    """Render the upload workflow with an explicit outcome.

    Returns:
        The upload form with a success or error message.
    """
    context = context_from_request(request)
    return context.templates.TemplateResponse(
        request,
        "upload.html",
        {"error": error, "msg": message},
    )


ROUTE_HANDLERS = (_ui_upload, _ui_upload_post)
