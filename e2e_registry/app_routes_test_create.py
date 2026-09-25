# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant API routes that create JSON and uploaded registry tests."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from e2e_registry import db as dbm
from e2e_registry.app_context import context_from_request
from e2e_registry.app_policy import form_checkbox_enabled, normalize_test_kind
from e2e_registry.auth import RequestAuth, require_tenant_auth
from e2e_registry.models import JsonObject
from e2e_registry.schema import CreateTestRequest
from e2e_registry.source_files import SourceFileError, store_source, validated_source_filename
from e2e_registry.stepflow import StepFlowValidationError, parse_definition_bytes, validate_definition

if TYPE_CHECKING:
    from e2e_registry.app_context import RegistryAppContext

router = APIRouter()
_RUNTIME_ANNOTATIONS = (Request, UploadFile, RequestAuth, JsonObject, CreateTestRequest)


@dataclass(frozen=True)
class _UploadIdentityForm:
    name: str = ""
    base_url: str = ""
    kind: str = ""
    notify_on_recovery: str = "0"
    dispatch_on_failure: str = "0"


@dataclass(frozen=True)
class _UploadScheduleForm:
    interval_seconds: int
    timeout_seconds: int
    jitter_seconds: int
    down_after_failures: int
    up_after_successes: int


@dataclass(frozen=True)
class _PreparedTest:
    name: str
    test_id: str | None = None
    definition: JsonObject | None = None
    source_relative_path: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None


def _upload_identity_form(
    name: Annotated[str, Form()] = "",
    base_url: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    notify_on_recovery: Annotated[str, Form()] = "0",
    dispatch_on_failure: Annotated[str, Form()] = "0",
) -> _UploadIdentityForm:
    fields = (name, base_url, kind, notify_on_recovery, dispatch_on_failure)
    return _UploadIdentityForm(*fields)


def _upload_schedule_form(
    interval_seconds: Annotated[int, Form()] = 300,
    timeout_seconds: Annotated[int, Form()] = 45,
    jitter_seconds: Annotated[int, Form()] = 30,
    down_after_failures: Annotated[int, Form()] = 2,
    up_after_successes: Annotated[int, Form()] = 2,
) -> _UploadScheduleForm:
    return _UploadScheduleForm(
        interval_seconds,
        timeout_seconds,
        jitter_seconds,
        down_after_failures,
        up_after_successes,
    )


def _validated_create_payload(
    context: RegistryAppContext,
    body: CreateTestRequest,
) -> tuple[str, JsonObject]:
    validated_url = context.base_url_policy.validate(body.base_url)
    definition = validate_definition(body.definition)
    return validated_url, definition


def _validated_uploaded_definition(content: bytes, *, content_type: str | None) -> JsonObject:
    raw_definition = parse_definition_bytes(content, content_type=content_type)
    return validate_definition(raw_definition)


def _prepare_stepflow_upload(
    *,
    content: bytes,
    content_type: str | None,
    supplied_name: str,
) -> _PreparedTest:
    definition = _validated_uploaded_definition(content, content_type=content_type)
    test_name = supplied_name.strip() or str(definition.get("name") or "test")
    return _PreparedTest(name=test_name, definition=definition)


def _prepare_code_upload(
    *,
    context: RegistryAppContext,
    tenant_id: str,
    normalized_kind: str,
    supplied_identity: tuple[str, str],
    content: bytes,
) -> _PreparedTest:
    supplied_name, supplied_filename = supplied_identity
    filename = validated_source_filename(normalized_kind, supplied_filename)
    test_id = str(uuid.uuid4())
    stored = store_source(
        context.settings,
        tenant_id=tenant_id,
        test_id=test_id,
        filename=filename,
        content=content,
    )
    return _PreparedTest(
        name=supplied_name.strip() or filename,
        test_id=test_id,
        source_relative_path=stored.relative_path,
        source_filename=stored.filename,
        source_sha256=stored.sha256,
    )


@router.post("/api/v1/tests")
async def _api_create_test(
    request: Request,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    body: CreateTestRequest | None = None,
) -> JsonObject:
    if body is None:
        raise HTTPException(status_code=400, detail="missing_body")
    context = context_from_request(request)
    try:
        base_url, definition = _validated_create_payload(context, body)
    except StepFlowValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created = await asyncio.to_thread(
        dbm.insert_test,
        context.settings,
        dbm.NewTest(
            tenant_id=auth.tenant_id,
            name=body.name,
            base_url=base_url,
            test_kind="stepflow",
            definition=definition,
            interval_seconds=body.interval_seconds,
            timeout_seconds=body.timeout_seconds,
            jitter_seconds=body.jitter_seconds,
            down_after_failures=body.down_after_failures,
            up_after_successes=body.up_after_successes,
            notify_on_recovery=body.notify_on_recovery,
            dispatch_on_failure=body.dispatch_on_failure,
        ),
    )
    return cast("JsonObject", {"ok": True, "test": created})


@router.post("/api/v1/tests/upload")
async def _api_upload_test(
    request: Request,
    auth: Annotated[RequestAuth, Depends(require_tenant_auth)],
    file: Annotated[UploadFile, File()],
    identity_form: Annotated[_UploadIdentityForm, Depends(_upload_identity_form)],
    schedule_form: Annotated[_UploadScheduleForm, Depends(_upload_schedule_form)],
) -> JsonObject:
    """Create a single-file code test or a StepFlow definition.

    Returns:
        The newly persisted test.

    Raises:
        HTTPException: If the form, target, or uploaded source is invalid.
    """
    context = context_from_request(request)
    normalized_kind = normalize_test_kind(identity_form.kind)
    if not normalized_kind:
        raise HTTPException(status_code=400, detail="invalid_kind")
    content = await file.read()
    if context.settings.max_upload_bytes > 0 and len(content) > context.settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file_too_large")
    validated_url = context.base_url_policy.validate(identity_form.base_url)
    notify = form_checkbox_enabled(identity_form.notify_on_recovery)
    dispatch = form_checkbox_enabled(identity_form.dispatch_on_failure)

    if normalized_kind == "stepflow":
        try:
            prepared = _prepare_stepflow_upload(
                content=content,
                content_type=file.content_type,
                supplied_name=identity_form.name,
            )
        except StepFlowValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        try:
            prepared = _prepare_code_upload(
                context=context,
                tenant_id=auth.tenant_id,
                normalized_kind=normalized_kind,
                supplied_identity=(identity_form.name, file.filename or ""),
                content=content,
            )
        except SourceFileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    created = await asyncio.to_thread(
        dbm.insert_test,
        context.settings,
        dbm.NewTest(
            tenant_id=auth.tenant_id,
            name=prepared.name,
            base_url=validated_url,
            test_id=prepared.test_id,
            test_kind=normalized_kind,
            definition=prepared.definition,
            source_relpath=prepared.source_relative_path,
            source_filename=prepared.source_filename,
            source_sha256=prepared.source_sha256,
            source_content_type=file.content_type,
            interval_seconds=schedule_form.interval_seconds,
            timeout_seconds=schedule_form.timeout_seconds,
            jitter_seconds=schedule_form.jitter_seconds,
            down_after_failures=schedule_form.down_after_failures,
            up_after_successes=schedule_form.up_after_successes,
            notify_on_recovery=notify,
            dispatch_on_failure=dispatch,
        ),
    )
    return cast("JsonObject", {"ok": True, "test": created})


ROUTE_HANDLERS = (_api_create_test, _api_upload_test)
