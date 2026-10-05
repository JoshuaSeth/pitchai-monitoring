# Copyright (c) 2026 PitchAI. All rights reserved.
"""Infrastructure gateway for read-only, bearer-authenticated JSON endpoints (standard library only).

Used by the host exporters for OpenCode Go plan usage and the DeepSeek API balance.

``urllib.request`` is reached through a typed dynamic boundary, the same way the
dashboard's other gateways reach httpx, so the exporter stays dependency-free on
the host's system Python 3.10.
"""

from __future__ import annotations

from contextlib import closing, suppress
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_BODY_BYTES = 65_536
TIMEOUT_SECONDS = 10.0
DEFAULT_AGENT = "pitchai-codex-usage/1"
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0"


class _Response(Protocol):
    """The two response methods the gateway uses."""

    def read(self, amount: int, /) -> bytes:
        """Read at most ``amount`` body bytes."""
        raise NotImplementedError

    def close(self) -> None:
        """Release the connection."""
        raise NotImplementedError


class _PreparedRequest(Protocol):
    """The ``urllib.request.Request`` surface the gateway relies on."""

    def get_method(self) -> str:
        """Return the HTTP method."""
        raise NotImplementedError

    def get_full_url(self) -> str:
        """Return the request URL."""
        raise NotImplementedError


class _RequestFactory(Protocol):
    """``urllib.request.Request`` with keyword headers."""

    def __call__(self, url: str, *, headers: Mapping[str, str]) -> _PreparedRequest:
        """Return one prepared request."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _UrlOpen(Protocol):
    """``urllib.request.urlopen`` with a keyword timeout."""

    def __call__(self, url: _PreparedRequest, *, timeout: float) -> _Response:
        """Open one prepared request."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


_URLLIB = vars(import_module("urllib.request"))
_REQUEST = cast("_RequestFactory", _URLLIB["Request"])
_URLOPEN = cast("_UrlOpen", _URLLIB["urlopen"])


def fetch_body(url: str, api_key: str, *, user_agent: str = DEFAULT_AGENT) -> bytes | None:
    """Return the raw response body of one bearer-authenticated GET, or nothing on any network failure."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": user_agent}
    body: bytes | None = None
    with (
        suppress(OSError),
        closing(_URLOPEN(_REQUEST(url, headers=headers), timeout=TIMEOUT_SECONDS)) as response,
    ):
        body = response.read(MAX_BODY_BYTES)
    return body
