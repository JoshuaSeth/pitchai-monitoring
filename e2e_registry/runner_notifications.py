# Copyright (c) 2026 PitchAI. All rights reserved.
"""Runner completion notifications emitted after durable state transitions."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from e2e_registry import db as dbm
from e2e_registry.alerts import (
    FailureAlertDetails,
    build_dispatch_prompt_for_failure,
    build_failure_telegram_message,
    build_recovery_telegram_message,
    maybe_send_failure_alert,
)
from e2e_registry.alerts_dispatch import maybe_dispatch_failure_investigation

if TYPE_CHECKING:
    from httpx import AsyncClient

    from e2e_registry.app_context import RegistryAppContext
    from e2e_registry.models import CompletionOutcome, DatabaseRecord, JsonObject
    from e2e_registry.schema import RunnerCompleteRequest


async def send_failure_notifications(
    *,
    context: RegistryAppContext,
    http_client: AsyncClient,
    run_id: str,
    body: RunnerCompleteRequest,
    outcome: CompletionOutcome,
) -> None:
    """Deliver threshold-triggered failure notifications after DB commit.

    Raises:
        RuntimeError: If the accepted completion references no stored test.
    """
    tenant_id, test_id, test_name = required_outcome_identity(outcome)
    config = await asyncio.to_thread(
        dbm.get_test_config_internal,
        context.settings,
        test_id=test_id,
    )
    if config is None:
        message = f"completed test config missing: {test_id}"
        raise RuntimeError(message)
    failure_details = failure_alert_details(
        identity=(tenant_id, test_id, test_name),
        run_id=run_id,
        body=body,
        outcome=outcome,
        config=config,
    )
    telegram_message = build_failure_telegram_message(
        settings=context.settings,
        details=failure_details,
    )
    await maybe_send_failure_alert(http_client=http_client, settings=context.settings, msg=telegram_message)
    if int(str(config["dispatch_on_failure"])) == 0:
        return
    await dispatch_failure_investigation(
        context=context,
        http_client=http_client,
        details=failure_details,
    )


def failure_alert_details(
    *,
    identity: tuple[str, str, str],
    run_id: str,
    body: RunnerCompleteRequest,
    outcome: CompletionOutcome,
    config: DatabaseRecord,
) -> FailureAlertDetails:
    """Build the immutable failure-notification payload from accepted state.

    Returns:
        The complete failure details used by every notification channel.
    """
    tenant_id, test_id, test_name = identity
    return FailureAlertDetails(
        tenant_id=tenant_id,
        test_id=test_id,
        test_name=test_name,
        test_kind=str(config["test_kind"]),
        base_url=str(config["base_url"]),
        run_id=run_id,
        fail_streak=int(outcome.fail_streak or 0),
        down_after_failures=int(str(config["down_after_failures"])),
        error_kind=body.error_kind,
        error_message=body.error_message,
        final_url=body.final_url,
        artifacts=body.artifacts,
    )


async def dispatch_failure_investigation(
    *,
    context: RegistryAppContext,
    http_client: AsyncClient,
    details: FailureAlertDetails,
) -> None:
    """Dispatch an investigation for an explicitly configured failure."""
    prompt = build_dispatch_prompt_for_failure(details=details)
    dispatch_context: JsonObject = {
        "tenant_id": details.tenant_id,
        "test_id": details.test_id,
        "test_name": details.test_name,
        "test_kind": details.test_kind,
        "base_url": details.base_url,
        "run_id": details.run_id,
    }
    await maybe_dispatch_failure_investigation(
        http_client=http_client,
        settings=context.settings,
        prompt=prompt,
        context=dispatch_context,
    )


async def send_recovery_notification(
    *,
    context: RegistryAppContext,
    http_client: AsyncClient,
    run_id: str,
    outcome: CompletionOutcome,
) -> None:
    """Deliver an explicitly configured recovery notification.

    Raises:
        RuntimeError: If the accepted completion references no stored test.
    """
    _tenant_id, test_id, test_name = required_outcome_identity(outcome)
    config = await asyncio.to_thread(
        dbm.get_test_config_internal,
        context.settings,
        test_id=test_id,
    )
    if config is None:
        message = f"recovered test config missing: {test_id}"
        raise RuntimeError(message)
    if int(str(config["notify_on_recovery"])) == 0:
        return
    telegram_message = build_recovery_telegram_message(
        settings=context.settings,
        test_id=test_id,
        test_name=test_name,
        run_id=run_id,
    )
    await maybe_send_failure_alert(http_client=http_client, settings=context.settings, msg=telegram_message)


def required_outcome_identity(outcome: CompletionOutcome) -> tuple[str, str, str]:
    """Return accepted completion identity or fail on an impossible alert outcome.

    Returns:
        Tenant ID, test ID, and test name.

    Raises:
        RuntimeError: If an alert transition lacks accepted completion identity.
    """
    if not outcome.updated or not outcome.tenant_id or not outcome.test_id or not outcome.test_name:
        message = "alert transition is missing accepted completion identity"
        raise RuntimeError(message)
    return outcome.tenant_id, outcome.test_id, outcome.test_name
