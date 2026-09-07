# Copyright (c) 2026 PitchAI. All rights reserved.
"""Authoritative broker and provider refreshes for organization decisions."""

from __future__ import annotations

import html
from functools import partial
from typing import TYPE_CHECKING, cast

from .clients import AccountScanError
from .guardian import Alert
from .models import utc_iso
from .organization_io import capture_io, safe_error_code
from .organization_runtime import OrganizationInventory

if TYPE_CHECKING:
    from .models import AccountDescriptor, AccountObservation
    from .organization_policy import RedemptionSelection
    from .organization_runtime import OrganizationRunContext


def refresh_organization(
    context: OrganizationRunContext,
    *,
    phase: str,
    selection: RedemptionSelection | None = None,
) -> OrganizationInventory:
    """Refresh every enabled broker account directly from its provider state.

    Returns:
        The complete descriptor set, successful observations, and failed account refs.

    Raises:
        RuntimeError: A captured broker call violates its value-or-error invariant.
    """
    listed = capture_io(context.source.list_accounts)
    if listed.error is not None:
        context.summary.error_count += 1
        context.audit.record_event(
            run_id=context.run_id,
            now=context.clock(),
            event_type="organization_account_inventory_refresh_failed",
            severity="error",
            details={"error_code": safe_error_code(listed.error), "phase": phase},
        )
        return OrganizationInventory((), {}, set(), inventory_failed=True)
    raw_descriptors = listed.value
    if raw_descriptors is None:
        message = "account listing returned neither a value nor an error"
        raise RuntimeError(message)
    descriptors = cast("list[AccountDescriptor]", raw_descriptors)
    observations: dict[str, AccountObservation] = {}
    failures: set[str] = set()
    for descriptor in descriptors:
        if not descriptor.enabled:
            continue
        refreshed = capture_io(partial(context.source.refresh_account, descriptor))
        if refreshed.error is not None:
            _record_refresh_failure(
                context,
                descriptor=descriptor,
                error=refreshed.error,
                phase=phase,
                selection=selection,
            )
            failures.add(descriptor.account_ref)
            continue
        raw_observation = refreshed.value
        if raw_observation is None:
            message = "account refresh returned neither a value nor an error"
            raise RuntimeError(message)
        observation = cast("AccountObservation", raw_observation)
        observations[descriptor.account_ref] = observation
        context.audit.record_snapshot(
            run_id=context.run_id,
            phase=phase,
            observation=observation,
        )
    return OrganizationInventory(tuple(descriptors), observations, failures)


def _record_refresh_failure(
    context: OrganizationRunContext,
    *,
    descriptor: AccountDescriptor,
    error: BaseException,
    phase: str,
    selection: RedemptionSelection | None,
) -> None:
    context.summary.error_count += 1
    broker_state = error.broker_state if isinstance(error, AccountScanError) else {}
    error_code = safe_error_code(error)
    context.audit.record_event(
        run_id=context.run_id,
        now=context.clock(),
        event_type="organization_account_refresh_failed",
        severity="error",
        account_ref=descriptor.account_ref,
        account_label=descriptor.label,
        details={
            "error_code": error_code,
            "broker_state": broker_state,
            "phase": phase,
        },
    )
    key = (
        f"account-error:{descriptor.account_ref}:{error_code}:"
        f"{context.clock().date().isoformat()}"
    )
    if selection is not None and selection.credit.expires_at is not None:
        key = (
            f"organization-recheck:{descriptor.account_ref}:"
            f"{selection.observation.descriptor.account_ref}:{selection.credit.credit_ref}:"
            f"{utc_iso(selection.credit.expires_at)}"
        )
    line = (
        f"ERROR {html.escape(descriptor.label)} could not be included in the "
        f"{html.escape(phase)} capacity proof."
    )
    context.alerts.append(Alert(key=key, line=line))
