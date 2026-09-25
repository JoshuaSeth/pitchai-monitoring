# Copyright (c) 2026 PitchAI. All rights reserved.
"""One-account model-catalog check boundary."""

from __future__ import annotations

from collections.abc import Callable

from .catalog import CatalogClient
from .catalog_transport import CatalogError
from .types import AccountCheck, BrokerAccount


def check_account(
    account: BrokerAccount,
    *,
    catalog_client: CatalogClient,
    client_version: str,
    timeout_seconds: float,
    wall_clock: Callable[[], str],
) -> AccountCheck:
    """Return one sanitized catalog outcome without refreshing authentication."""
    checked_at = wall_clock()
    if account.availability.casefold() == "auth_invalid":
        return AccountCheck(
            account,
            checked_at,
            None,
            (),
            None,
            0,
            unavailable_reason="broker_auth_invalid",
        )
    if account.error_code:
        return AccountCheck(account, checked_at, None, (), account.error_code, 0)
    try:
        result = catalog_client.fetch(
            account,
            client_version=client_version,
            timeout_seconds=timeout_seconds,
        )
    except CatalogError as exc:
        return AccountCheck(
            account,
            checked_at,
            None,
            (),
            exc.error_code,
            exc.provider_request_count,
        )
    return AccountCheck(
        account,
        checked_at,
        result.model_count,
        result.matches,
        None,
        1,
    )
