# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exact read-only Codex model-catalog client and ASTRA parser."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, final

from .catalog_transport import (
    CATALOG_BASE_URL,
    CATALOG_HOST,
    CATALOG_PATH,
    CATALOG_SCHEME,
    SAFE_TRANSPORT_CONTRACT,
    CatalogError,
    DirectHttpsCatalogTransport,
)
from .json_types import JsonObject, object_list, string_object_dict
from .types import CatalogResult, ModelMatch

if TYPE_CHECKING:
    from .catalog_transport import CatalogTransport
    from .types import BrokerAccount

MODEL_ID_NAME_FIELDS = (
    "slug",
    "id",
    "model",
    "name",
    "display_name",
    "displayName",
    "title",
)
FORBIDDEN_PATH_MARKERS = (
    "reset",
    "credit",
    "consume",
    "redeem",
    "claim",
    "activate",
    "oauth",
    "lease",
    "response",
    "task",
    "wham",
)


def catalog_url(client_version: str) -> str:
    """Build and validate the sole provider URL this monitor may call."""
    version = client_version.strip()
    if (
        not version
        or len(version) > 64
        or any(char not in "0123456789.-+" for char in version)
    ):
        raise CatalogError("invalid_client_version")
    url = f"{CATALOG_BASE_URL}?{urllib.parse.urlencode({'client_version': version})}"
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    checks = (
        parsed.scheme == CATALOG_SCHEME,
        parsed.hostname == CATALOG_HOST,
        parsed.port is None,
        parsed.path == CATALOG_PATH,
        not parsed.fragment,
        parsed.username is None,
        parsed.password is None,
        set(query) == {"client_version"},
        query.get("client_version") == [version],
        not any(marker in parsed.path.casefold() for marker in FORBIDDEN_PATH_MARKERS),
    )
    if not all(checks):
        raise CatalogError("unsafe_catalog_url")
    return url


def _parse_catalog(payload: JsonObject, etag_present: bool) -> CatalogResult:
    raw_models = object_list(payload.get("models"))
    if raw_models is None:
        raise CatalogError("missing_models_array", provider_request_count=1)
    matches: list[ModelMatch] = []
    for index, raw_model in enumerate(raw_models):
        model = string_object_dict(raw_model)
        if model is None:
            raise CatalogError("invalid_model_entry", provider_request_count=1)
        values: list[tuple[str, str]] = []
        for field_name in MODEL_ID_NAME_FIELDS:
            value = model.get(field_name)
            if isinstance(value, str) and value.strip():
                safe_model_text = " ".join(value.split())[:240]
                values.append((field_name, safe_model_text))
        matched: list[tuple[str, str]] = []
        for field_name, value in values:
            if "astra" in value.casefold():
                matched.append((field_name, value))
        if not matched:
            continue
        identifier = None
        for field_name, value in values:
            if field_name == "slug":
                identifier = value
                break
        if identifier is None:
            identifier = values[0][1] if values else f"catalog-index-{index}"
        matched_fields: list[str] = []
        matched_values: list[str] = []
        for field_name, value in matched:
            matched_fields.append(field_name)
            matched_values.append(value)
        matches.append(
            ModelMatch(
                identifier=identifier,
                matched_fields=tuple(matched_fields),
                matched_values=tuple(matched_values),
            ),
        )
    return CatalogResult(
        model_count=len(raw_models),
        matches=tuple(matches),
        etag_present=etag_present,
    )


@final
class CatalogClient:
    """Fetch an account catalog only through the attested direct transport."""

    def __init__(self, transport: CatalogTransport | None = None) -> None:
        self.transport = transport or DirectHttpsCatalogTransport()
        if self.transport.safety_contract != SAFE_TRANSPORT_CONTRACT:
            raise CatalogError("unsafe_transport_contract")

    @staticmethod
    def endpoint_url(client_version: str) -> str:
        """Return the sole permitted endpoint for a client version."""
        return catalog_url(client_version)

    def fetch(
        self,
        account: BrokerAccount,
        *,
        client_version: str,
        timeout_seconds: float,
    ) -> CatalogResult:
        """Fetch and scan one account's catalog with its existing bearer only."""
        if not account.access_token or not account.account_header_id:
            raise CatalogError("account_auth_unavailable")
        url = self.endpoint_url(client_version)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {account.access_token}",
            "Cache-Control": "no-cache",
            "ChatGPT-Account-ID": account.account_header_id,
            "User-Agent": f"codex-cli/{client_version} pitchai-astra-model-watch",
        }
        payload, etag_present = self.transport.get_json(
            url=url,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
        return _parse_catalog(payload, etag_present)
