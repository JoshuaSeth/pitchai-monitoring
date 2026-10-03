# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed existing dispatch metric routes; no new audience or trigger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from .dispatch_context import DispatchInputs, DispatchRequest, DispatchRuntime
from .dispatch_workflow import run_dispatch
from .message_slo_red import build_red_dispatch_prompt, build_slo_dispatch_prompt
from .message_tls_dns import build_dns_dispatch_prompt, build_tls_dispatch_prompt

if TYPE_CHECKING:
    from .metrics_dns import DnsCheckResult
    from .metrics_red import RedViolation
    from .metrics_slo import SloBurnViolation
    from .metrics_tls import TlsCertCheckResult


class TlsInputs(DispatchInputs):
    """Existing tls dispatch keyword payload."""

    results: list[TlsCertCheckResult]
    min_days_valid: float


class DnsInputs(DispatchInputs):
    """Existing dns dispatch keyword payload."""

    results: list[DnsCheckResult]


class SloInputs(DispatchInputs):
    """Existing slo dispatch keyword payload."""

    violations: list[SloBurnViolation]
    slo_target_percent: float


class RedInputs(DispatchInputs):
    """Existing red dispatch keyword payload."""

    violations: list[RedViolation]
    window_minutes: int


async def dispatch_tls_and_forward(**inputs: Unpack[TlsInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_tls_dispatch_prompt(results=inputs["results"], min_days_valid=inputs["min_days_valid"])
    request = DispatchRequest(prompt, "service-monitoring.tls", "TLS investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_dns_and_forward(**inputs: Unpack[DnsInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_dns_dispatch_prompt(results=inputs["results"])
    request = DispatchRequest(prompt, "service-monitoring.dns", "DNS investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_slo_and_forward(**inputs: Unpack[SloInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_slo_dispatch_prompt(violations=inputs["violations"], slo_target_percent=inputs["slo_target_percent"])
    request = DispatchRequest(prompt, "service-monitoring.slo", "SLO burn investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_red_and_forward(**inputs: Unpack[RedInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_red_dispatch_prompt(violations=inputs["violations"], window_minutes=inputs["window_minutes"])
    request = DispatchRequest(prompt, "service-monitoring.red", "RED signals investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)
