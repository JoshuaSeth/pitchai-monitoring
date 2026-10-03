# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing API-contract dispatch identity and typed record references."""

from __future__ import annotations

from typing import TYPE_CHECKING, Unpack

from .dispatch_context import DispatchInputs, DispatchRequest, DispatchRuntime
from .dispatch_workflow import run_dispatch
from .message_api_contract import build_api_contract_dispatch_prompt

if TYPE_CHECKING:
    from .metrics_api_contract import ApiContractCheckResult


class ApiDispatchInputs(DispatchInputs):
    """The unchanged keyword payload for the API investigation workflow."""

    failures: list[ApiContractCheckResult]


async def dispatch_api_contract_and_forward(**inputs: Unpack[ApiDispatchInputs]) -> None:
    """Use the configured dispatcher and collections with the original prompt."""
    prompt = build_api_contract_dispatch_prompt(failures=inputs["failures"])
    request = DispatchRequest(prompt, "service-monitoring.api_contract", "API contract investigation")
    runtime = DispatchRuntime.from_inputs(inputs)
    await run_dispatch(runtime, request)
