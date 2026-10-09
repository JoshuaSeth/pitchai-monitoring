# Copyright (c) 2026 PitchAI. All rights reserved.
"""Registry failure text using the monitor's shared diagnostic safety contract."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack

from domain_checks.message_templates import dispatch_read_only_rules

if TYPE_CHECKING:
    from domain_checks.event_bus_delivery import JsonObject, JsonValue

    from .settings import RegistrySettings


class FailureMessageInputs(TypedDict):
    """Existing keyword-only failure message arguments, including unused tenant ID."""

    settings: RegistrySettings
    tenant_id: str
    test_id: str
    test_name: str
    test_kind: NotRequired[str | None]
    run_id: str
    fail_streak: int
    down_after_failures: int
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    artifacts: JsonObject | None


class FailurePromptInputs(TypedDict):
    """Existing submitted-test dispatch prompt arguments."""

    test_id: str
    test_name: str
    test_kind: NotRequired[str | None]
    base_url: str
    run_id: str
    error_kind: str | None
    error_message: str | None
    artifacts: JsonObject | None


def safe_json(value: JsonValue, *, max_len: int = 20_000) -> str:
    """Serialize the existing JSON payload, retaining text fallback and truncation.

    Returns:
        Indented JSON or the original best-effort string representation.
    """
    rendered = None
    # Serialization remains best effort at the diagnostic-text boundary.
    with suppress(Exception):
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    text = str(value) if rendered is None else rendered
    return text if len(text) <= max_len else text[:max_len] + "\n...truncated..."


def public_url(settings: RegistrySettings, path: str) -> str:
    """Retain relative links when no public base is configured.

    Returns:
        The existing slash-normalized UI link.
    """
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return path
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def artifact_names(artifacts: JsonValue) -> list[str]:
    """Select the three recognized artifact names in their existing order.

    Returns:
        Names whose recorded paths are nonblank strings.
    """
    names: list[str] = []
    if artifacts and isinstance(artifacts, dict):
        for key in ("failure_screenshot", "trace_zip", "run_log"):
            value = artifacts.get(key)
            if isinstance(value, str) and value.strip():
                names.append(key)
    return names


def build_failure_telegram_message(**inputs: Unpack[FailureMessageInputs]) -> str:
    """Construct existing failure text without choosing or invoking a transport.

    Returns:
        The complete external-test failure message.
    """
    settings = inputs["settings"]
    test_id, run_id = inputs["test_id"], inputs["run_id"]
    lines = ["External E2E test is FAILING ❌", f"Test: {inputs['test_name']}",
             f"Test ID: {test_id}", f"Run ID: {run_id}"]
    if test_kind := inputs.get("test_kind"):
        lines.append(f"Kind: {str(test_kind)[:40]}")
    if inputs["down_after_failures"] > 1:
        lines.append(f"Debounce: fail_streak={int(inputs['fail_streak'])}/{int(inputs['down_after_failures'])}")
    if error_kind := inputs["error_kind"]:
        lines.append(f"Error kind: {str(error_kind)[:120]}")
    if error_message := inputs["error_message"]:
        lines.append(f"Error: {str(error_message)[:500]}")
    if final_url := inputs["final_url"]:
        lines.append(f"Final URL: {str(final_url)[:800]}")
    lines.extend([f"UI: {public_url(settings, f'/ui/runs/{run_id}')}",
                  f"Test: {public_url(settings, f'/ui/tests/{test_id}')}"])
    names = artifact_names(inputs["artifacts"])
    if names:
        lines.append(f"Artifacts: {', '.join(names)}")
    return "\n".join(lines).strip()


def build_recovery_telegram_message(
    *, settings: RegistrySettings, test_id: str, test_name: str, run_id: str,
) -> str:
    """Construct the existing recovered message without sending it.

    Returns:
        The original message with its stable run link.
    """
    run_link = public_url(settings, f"/ui/runs/{run_id}")
    return "\n".join([
        "External E2E test RECOVERED ✅", f"Test: {test_name}", f"Test ID: {test_id}", f"Run: {run_link}",
    ]).strip()


def build_dispatch_prompt_for_failure(**inputs: Unpack[FailurePromptInputs]) -> str:
    """Use the shared monitor safety rules with unchanged registry task text.

    Returns:
        The existing bounded read-only investigation prompt.
    """
    payload: JsonObject = {
        "test_id": inputs["test_id"], "test_name": inputs["test_name"],
        "test_kind": inputs.get("test_kind"), "base_url": inputs["base_url"],
        "run_id": inputs["run_id"], "error_kind": inputs["error_kind"],
        "error_message": inputs["error_message"], "artifacts": inputs["artifacts"] or {},
    }
    return (
        "An external developer-submitted end-to-end UI test is failing.\n\n"
        "Failure details (JSON):\n"
        f"{safe_json(payload)}\n\n"
        f"{dispatch_read_only_rules()}\n"
        "Task:\n"
        "1) Determine whether the failure is a real product regression vs monitoring/infra instability.\n"
        "2) Reproduce from the production host with curl and, if needed, Playwright in headless mode.\n"
        "3) Inspect relevant containers, reverse proxy, logs, and recent deploys.\n"
        "4) Provide a remediation plan for a human operator (no changes executed).\n\n"
        "Return a concise final report with:\n"
        "- Root cause + evidence\n"
        "- Reproduction steps\n"
        "- Scope/impact (which service/domain)\n"
        "- Suggested safe next actions\n"
    )
