# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed existing dispatch probe routes; no new audience or trigger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from .dispatch_context import DispatchInputs, DispatchRequest, DispatchRuntime
from .dispatch_workflow import run_dispatch
from .message_browser import build_synthetic_dispatch_prompt, build_web_vitals_dispatch_prompt
from .message_container import build_container_health_dispatch_prompt
from .message_proxy import build_proxy_dispatch_prompt

if TYPE_CHECKING:
    from .metrics_container_health import ContainerHealthIssue
    from .metrics_nginx import NginxAccessWindowStats, NginxUpstreamErrorEvent
    from .metrics_proxy import ProxyIssue
    from .metrics_synthetic import SyntheticTransactionResult
    from .metrics_web_vitals import WebVitalsResult


class SyntheticInputs(DispatchInputs):
    """Existing synthetic dispatch keyword payload."""

    failures: list[SyntheticTransactionResult]


class WebVitalsInputs(DispatchInputs):
    """Existing web vitals dispatch keyword payload."""

    failures: list[WebVitalsResult]


class ContainerHealthInputs(DispatchInputs):
    """Existing container health dispatch keyword payload."""

    issues: list[ContainerHealthIssue]


class ProxyInputs(DispatchInputs):
    """Existing proxy dispatch keyword payload."""

    upstream_issues: list[ProxyIssue]
    access_stats: NginxAccessWindowStats | None
    upstream_error_events: list[NginxUpstreamErrorEvent]
    window_seconds: int


async def dispatch_synthetic_and_forward(**inputs: Unpack[SyntheticInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_synthetic_dispatch_prompt(failures=inputs["failures"])
    request = DispatchRequest(prompt, "service-monitoring.synthetic", "Synthetic transactions investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_web_vitals_and_forward(**inputs: Unpack[WebVitalsInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_web_vitals_dispatch_prompt(failures=inputs["failures"])
    request = DispatchRequest(prompt, "service-monitoring.web_vitals", "Web vitals investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_container_health_and_forward(**inputs: Unpack[ContainerHealthInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_container_health_dispatch_prompt(issues=inputs["issues"])
    request = DispatchRequest(prompt, "service-monitoring.container_health", "Container health investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)


async def dispatch_proxy_and_forward(**inputs: Unpack[ProxyInputs]) -> None:
    """Map this existing check result to its unchanged dispatch identity."""
    prompt = build_proxy_dispatch_prompt(
        upstream_issues=inputs["upstream_issues"],
        access_stats=inputs["access_stats"],
        upstream_error_events=inputs["upstream_error_events"],
        window_seconds=inputs["window_seconds"],
    )
    request = DispatchRequest(prompt, "service-monitoring.proxy", "Proxy/upstream investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)
