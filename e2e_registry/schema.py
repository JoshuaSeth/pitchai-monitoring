from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ApiError


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class CreateApiKeyRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)


class CreateTestRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_url: str = Field(..., min_length=1, max_length=2000)
    definition: dict[str, Any]

    interval_seconds: int = Field(300, ge=60, le=3600)
    timeout_seconds: int = Field(45, ge=5, le=300)
    jitter_seconds: int = Field(30, ge=0, le=300)

    down_after_failures: int = Field(2, ge=1, le=20)
    up_after_successes: int = Field(2, ge=1, le=20)
    notify_on_recovery: bool = False
    dispatch_on_failure: bool = False


class PatchTestRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    base_url: str | None = Field(None, min_length=1, max_length=2000)
    definition: dict[str, Any] | None = None

    interval_seconds: int | None = Field(None, ge=60, le=3600)
    timeout_seconds: int | None = Field(None, ge=5, le=300)
    jitter_seconds: int | None = Field(None, ge=0, le=300)

    down_after_failures: int | None = Field(None, ge=1, le=20)
    up_after_successes: int | None = Field(None, ge=1, le=20)
    notify_on_recovery: bool | None = None
    dispatch_on_failure: bool | None = None


class DisableTestRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
    until: str | float | int | None = None  # unix ts or ISO datetime/date


class RunnerClaimRequest(BaseModel):
    max_runs: int = Field(1, ge=1, le=50)


class RunnerCompleteRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=30)  # pass|fail|infra_degraded
    elapsed_ms: float | None = None
    error_kind: str | None = Field(None, max_length=120)
    error_message: str | None = Field(None, max_length=2000)
    final_url: str | None = Field(None, max_length=2000)
    title: str | None = Field(None, max_length=500)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    started_at_ts: float | None = None
    finished_at_ts: float | None = None

