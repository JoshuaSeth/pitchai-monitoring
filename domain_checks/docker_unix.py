# Copyright (c) 2026 PitchAI. All rights reserved.
"""PitchAI domain monitoring support for docker unix."""

from __future__ import annotations

import http.client
import json
import logging
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, final, override

if TYPE_CHECKING:
    from domain_checks.types import JsonValue


LOGGER = logging.getLogger(__name__)
_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX_EXCLUSIVE = 300


@final
class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    @override
    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


@dataclass(frozen=True)
class DockerUnixResponse:
    """Represent DockerUnixResponse."""

    status: int
    ok: bool
    data: JsonValue
    error: str | None


def _decode_body(raw: bytes) -> JsonValue:
    if not raw:
        return None
    try:
        return cast("JsonValue", json.loads(raw.decode("utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _request_json(conn: _UnixHTTPConnection, path: str) -> DockerUnixResponse:
    conn.request("GET", path, headers={"Host": "docker"})
    response = conn.getresponse()
    raw = response.read()
    status = int(response.status)
    data = _decode_body(raw)
    ok = _HTTP_SUCCESS_MIN <= status < _HTTP_SUCCESS_MAX_EXCLUSIVE
    return DockerUnixResponse(
        status=status,
        ok=ok,
        data=data,
        error=None if ok else f"http_{status}",
    )


def _request_with_connection(
    *,
    socket_path: str,
    path: str,
    timeout_seconds: float,
) -> DockerUnixResponse:
    conn = _UnixHTTPConnection(
        socket_path=socket_path,
        timeout=max(0.5, float(timeout_seconds)),
    )
    try:
        return _request_json(conn, path)
    finally:
        try:
            conn.close()
        except OSError:
            LOGGER.debug(
                "Failed to close Docker Unix-socket connection",
                exc_info=True,
            )


def docker_unix_get_json(
    *,
    socket_path: str,
    path: str,
    timeout_seconds: float = 5.0,
) -> DockerUnixResponse:
    """Minimal Docker Engine API client over /var/run/docker.sock.

    We intentionally avoid docker CLI and third-party libs inside the monitor container.

    Returns:
        The decoded Docker response or a bounded transport failure.
    """
    sp = str(socket_path or "").strip()
    if not sp:
        return DockerUnixResponse(
            status=0,
            ok=False,
            data=None,
            error="missing_socket_path",
        )
    p = str(path or "").strip()
    if not p.startswith("/"):
        p = "/" + p

    try:
        return _request_with_connection(
            socket_path=sp,
            path=p,
            timeout_seconds=timeout_seconds,
        )
    except FileNotFoundError:
        return DockerUnixResponse(
            status=0,
            ok=False,
            data=None,
            error="socket_not_found",
        )
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return DockerUnixResponse(
            status=0,
            ok=False,
            data=None,
            error=f"{type(exc).__name__}: {exc}",
        )
