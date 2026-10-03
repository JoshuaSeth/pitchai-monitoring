# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed existing dispatch domain routes; no new audience or trigger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from .dispatch_context import DispatchInputs, DispatchRequest, DispatchRuntime
from .dispatch_workflow import run_dispatch
from .message_performance import build_performance_dispatch_prompt
from .message_templates import build_dispatch_prompt, build_host_health_dispatch_prompt, build_meta_dispatch_prompt

if TYPE_CHECKING:
    from .common_check import DomainCheckResult
    from .event_bus_delivery import JsonObject


class DomainInputs(DispatchInputs):
    """Existing domain dispatch keyword payload."""

    result: DomainCheckResult


class HostHealthInputs(DispatchInputs):
    """Existing host health dispatch keyword payload."""

    violations: list[str]
    snap: JsonObject


class PerformanceInputs(DispatchInputs):
    """Existing performance dispatch keyword payload."""

    slow: list[JsonObject]


class MetaInputs(DispatchInputs):
    """Existing meta dispatch keyword payload."""

    reasons: list[str]
    context: JsonObject


async def dispatch_and_forward(**inputs: Unpack[DomainInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_dispatch_prompt(inputs["result"])
    request = DispatchRequest(
        prompt, f"service-monitoring.{inputs['result'].domain}", f"{inputs['result'].domain} investigation",
    )
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_host_health_and_forward(**inputs: Unpack[HostHealthInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_host_health_dispatch_prompt(violations=inputs["violations"], snap=inputs["snap"])
    request = DispatchRequest(prompt, "service-monitoring.host_health", "Host health investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_performance_and_forward(**inputs: Unpack[PerformanceInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_performance_dispatch_prompt(slow=inputs["slow"])
    request = DispatchRequest(prompt, "service-monitoring.performance", "Performance investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_meta_and_forward(**inputs: Unpack[MetaInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_meta_dispatch_prompt(reasons=inputs["reasons"], context=inputs["context"])
    request = DispatchRequest(prompt, "service-monitoring.meta", "Monitoring pipeline investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)
