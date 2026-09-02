# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded HTTPS infrastructure gateway for the central scheduler feed."""

from __future__ import annotations

import json
from contextlib import closing
from http.client import HTTPConnection, HTTPSConnection
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode, urlparse

from .json_types import json_object

if TYPE_CHECKING:
    from .json_types import JsonInput, JsonObject

_HTTP_OK = 200
_MAX_RESPONSE_BYTES = 262_144
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def read_scheduler_json(
    *,
    url: str,
    token: str,
    timeout_seconds: float,
    query: dict[str, str],
) -> JsonObject:
    """Read one authenticated, bounded central scheduler document.

    Returns:
        A normalized JSON response object.

    Raises:
        RuntimeError: If the HTTPS response is unsuccessful or too large.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    loopback_http = parsed.scheme == "http" and hostname in _LOOPBACK_HOSTS
    if (parsed.scheme != "https" and not loopback_http) or hostname is None or parsed.username or parsed.password:
        message = "scheduler incident gateway requires HTTPS or exact loopback HTTP without userinfo"
        raise RuntimeError(message)
    request_path = parsed.path or "/"
    encoded_query = urlencode(query)
    if encoded_query:
        request_path = f"{request_path}?{encoded_query}"
    connection_class = HTTPConnection if loopback_http else HTTPSConnection
    connection = connection_class(hostname, port=parsed.port, timeout=timeout_seconds)
    with closing(connection):
        connection.request(
            "GET",
            request_path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "PitchAI Scheduler Observer",
            },
        )
        response = connection.getresponse()
        content_length = response.getheader("Content-Length")
        if content_length is not None and content_length.isdecimal() and int(content_length) > _MAX_RESPONSE_BYTES:
            message = "scheduler incident feed response exceeded its bounded size"
            raise RuntimeError(message)
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        message = "scheduler incident feed response exceeded its bounded size"
        raise RuntimeError(message)
    if response.status != _HTTP_OK:
        message = f"scheduler incident feed failed with HTTP {response.status}"
        raise RuntimeError(message)
    decoded = cast("JsonInput", json.loads(body.decode("utf-8")))
    return json_object(decoded)
