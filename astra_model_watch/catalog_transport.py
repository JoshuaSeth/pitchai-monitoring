# Copyright (c) 2026 PitchAI. All rights reserved.
"""Direct, bodyless, redirect-free HTTPS transport for the Codex catalog."""

from __future__ import annotations

import json
import urllib.parse
from contextlib import closing
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from typing import TYPE_CHECKING, Protocol, cast, final

from .json_types import JsonObject, string_object_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .json_types import UntrustedValue

CATALOG_SCHEME = "https"
CATALOG_HOST = "chatgpt.com"
CATALOG_PATH = "/backend-api/codex/models"
CATALOG_BASE_URL = f"{CATALOG_SCHEME}://{CATALOG_HOST}{CATALOG_PATH}"
MAX_CATALOG_BYTES = 5 * 1024 * 1024
SAFE_TRANSPORT_CONTRACT = (
    "method=GET",
    f"origin={CATALOG_SCHEME}://{CATALOG_HOST}",
    f"path={CATALOG_PATH}",
    "body=none",
    "redirects=refused",
    "proxies=disabled",
    "cookies=disabled",
)


@final
class CatalogError(RuntimeError):
    """A sanitized catalog failure that never includes response or credential data."""

    def __init__(self, error_code: str, *, provider_request_count: int = 0):
        super().__init__(error_code)
        self.error_code = error_code
        self.provider_request_count = provider_request_count


class CatalogTransport(Protocol):
    """Transport restricted to one JSON GET and an auditable safety contract."""

    @property
    def safety_contract(self) -> tuple[str, ...]:
        """Return the immutable transport safety declaration."""
        raise NotImplementedError

    def get_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[JsonObject, bool]:
        """Return a JSON object plus whether the response supplied an ETag."""
        raise NotImplementedError


@final
class DirectHttpsCatalogTransport:
    """Cookie-free direct HTTPS transport that cannot follow redirects."""

    @property
    def safety_contract(self) -> tuple[str, ...]:
        """Return the direct transport's enforced safety declaration."""
        return SAFE_TRANSPORT_CONTRACT

    def get_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[JsonObject, bool]:
        """Issue the sole direct model-list GET and decode its bounded response."""
        try:
            return self._exchange(url, headers, timeout_seconds)
        except (HTTPException, OSError) as exc:
            raise CatalogError(
                f"transport_{type(exc).__name__}",
                provider_request_count=1,
            ) from None

    @staticmethod
    def _exchange(
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[JsonObject, bool]:
        parsed = urllib.parse.urlsplit(url)
        expected_origin = f"{CATALOG_SCHEME}://{CATALOG_HOST}"
        if (
            f"{parsed.scheme}://{parsed.netloc}" != expected_origin
            or parsed.path != CATALOG_PATH
        ):
            raise CatalogError("unsafe_transport_url")
        target = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
        with closing(
            HTTPSConnection(CATALOG_HOST, timeout=timeout_seconds),
        ) as connection:
            connection.request("GET", target, body=None, headers=dict(headers))
            with connection.getresponse() as response:
                return DirectHttpsCatalogTransport._decode_response(response)

    @staticmethod
    def _decode_response(response: HTTPResponse) -> tuple[JsonObject, bool]:
        if 300 <= response.status < 400:
            raise CatalogError("redirect_refused", provider_request_count=1)
        if response.status != 200:
            raise CatalogError(f"http_{response.status}", provider_request_count=1)
        raw = response.read(MAX_CATALOG_BYTES + 1)
        etag_present = response.headers.get("ETag") is not None
        if len(raw) > MAX_CATALOG_BYTES:
            raise CatalogError("response_too_large", provider_request_count=1)
        try:
            payload = cast("UntrustedValue", json.loads(raw))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CatalogError("invalid_json", provider_request_count=1) from None
        typed_payload = string_object_dict(payload)
        if typed_payload is None:
            raise CatalogError("invalid_payload", provider_request_count=1)
        return typed_payload, etag_present
