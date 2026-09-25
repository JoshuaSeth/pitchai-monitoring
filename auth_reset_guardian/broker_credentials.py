# Copyright (c) 2026 PitchAI. All rights reserved.
"""Load broker-managed provider credentials and build safe headers."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from .client_http import AccountScanError, JsonRequest
from .models import ProviderCredentials

if TYPE_CHECKING:
    from .client_http import JsonHttpTransport
    from .json_contract import JsonObject
    from .models import AccountDescriptor


class BrokerCredentialContext(NamedTuple):
    """Bundle one broker credential export request's trusted context."""

    broker_url: str
    account_path: str
    descriptor: AccountDescriptor
    broker_state: JsonObject
    broker_headers: dict[str, str]


def request_provider_credentials(
    request: JsonHttpTransport,
    context: BrokerCredentialContext,
) -> ProviderCredentials:
    """Load and validate one broker account's provider credentials.

    Returns:
        The validated credentials.

    Raises:
        AccountScanError: If required broker credential fields are unavailable.

    """
    auth_json = request(
        JsonRequest(
            method="GET",
            url=(
                f"{context.broker_url}/v1/admin/accounts/"
                f"{context.account_path}/auth.json"
            ),
            endpoint="broker_export_auth",
            headers=context.broker_headers,
        ),
    )
    tokens = auth_json.get("tokens")
    if not isinstance(tokens, dict):
        raise AccountScanError(
            descriptor=context.descriptor,
            error_code="broker_auth_tokens_missing",
            broker_state=context.broker_state,
        )
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not isinstance(access_token, str) or not access_token.strip():
        raise AccountScanError(
            descriptor=context.descriptor,
            error_code="broker_access_token_missing",
            broker_state=context.broker_state,
        )
    if not isinstance(account_id, str) or not account_id.strip():
        raise AccountScanError(
            descriptor=context.descriptor,
            error_code="broker_chatgpt_account_id_missing",
            broker_state=context.broker_state,
        )
    return ProviderCredentials(
        access_token=access_token.strip(),
        account_id=account_id.strip(),
    )


def provider_headers(credentials: ProviderCredentials) -> dict[str, str]:
    """Build one provider request header set from validated credentials.

    Returns:
        The provider request headers.

    """
    return {
        "Authorization": f"Bearer {credentials.access_token}",
        "ChatGPT-Account-Id": credentials.account_id,
        "Accept": "application/json",
        "User-Agent": "pitchai-auth-reset-guardian",
    }
