# Copyright (c) 2026 PitchAI. All rights reserved.
"""Minimal bounded Docker Engine gateway for in-container probes."""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from functools import partial
from http.client import HTTPConnection
from socket import AF_UNIX, SOCK_STREAM
from socket import socket as open_socket
from typing import TYPE_CHECKING, cast, final, override
from urllib.parse import quote

from monitoring_contracts.json_types import int_value, json_object, normalize_json, text_value

from .docker_errors import DockerProtocolError
from .docker_frames import decode_multiplexed_stream
from .models import ProbeExecution

if TYPE_CHECKING:
    from monitoring_contracts.json_types import JsonInput, JsonObject, JsonValue

_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_NOT_FOUND = 404
_MAX_CONTAINER_LIST_BYTES = 2_097_152
_MAX_CONTAINER_INSPECT_BYTES = 1_048_576
_MAX_EXEC_CONTROL_BYTES = 65_536
_MAX_EXEC_OUTPUT_BYTES = 65_536


@final
class _UnixHTTPConnection(HTTPConnection):
    """HTTP connection transported over one Unix socket."""

    def __init__(self, *, socket_path: str, timeout_seconds: float) -> None:
        super().__init__("localhost", timeout=timeout_seconds)
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds

    @override
    def connect(self) -> None:
        socket_factory = partial(open_socket, AF_UNIX, SOCK_STREAM)
        unix_socket = socket_factory()
        unix_socket.settimeout(self._timeout_seconds)
        unix_socket.connect(self._socket_path)
        self.sock = unix_socket


@dataclass(frozen=True)
class _DockerResponse:
    """One bounded Docker API response."""

    status: int
    body: bytes


@final
class DockerGateway:
    """Execute exact Docker API calls without a Docker CLI dependency."""

    def __init__(self, *, socket_path: str, timeout_seconds: float) -> None:
        """Configure the Docker Unix-socket boundary and request timeout."""
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds

    def _request(
        self,
        *,
        method: str,
        path: str,
        max_body_bytes: int,
        body: JsonObject | None = None,
    ) -> _DockerResponse:
        encoded = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {
            "Host": "docker",
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
        connection = _UnixHTTPConnection(
            socket_path=self._socket_path,
            timeout_seconds=self._timeout_seconds,
        )
        with closing(connection):
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            content_length = response.getheader("Content-Length")
            if content_length is not None and content_length.isdigit() and int(content_length) > max_body_bytes:
                message = "Docker response exceeded its configured boundary"
                raise DockerProtocolError(message)
            payload = response.read(max_body_bytes + 1)
            if len(payload) > max_body_bytes:
                message = "Docker response exceeded its configured boundary"
                raise DockerProtocolError(message)
            return _DockerResponse(status=response.status, body=payload)

    @staticmethod
    def _json_body(response: _DockerResponse) -> JsonValue:
        if not response.body:
            return None
        decoded_text = response.body.decode("utf-8")
        decoded = cast("JsonInput", json.loads(decoded_text))
        return normalize_json(decoded)

    def running_containers(self) -> list[JsonObject]:
        """Return normalized running-container summaries.

        Returns:
            Normalized Docker inventory entries.

        Raises:
            DockerProtocolError: If Docker returns an invalid inventory response.
        """
        response = self._request(
            method="GET",
            path="/containers/json?all=false",
            max_body_bytes=_MAX_CONTAINER_LIST_BYTES,
        )
        if response.status != _HTTP_OK:
            message = f"Docker running-container inventory failed with HTTP {response.status}"
            raise DockerProtocolError(message)
        payload = self._json_body(response)
        if not isinstance(payload, list):
            message = "Docker running-container inventory was not an array"
            raise DockerProtocolError(message)
        return [json_object(item) for item in payload]

    def inspect_container(self, container_id: str) -> JsonObject:
        """Return one running container's bounded configuration.

        Returns:
            The normalized Docker container inspection payload.

        Raises:
            DockerProtocolError: If Docker returns an invalid inspection response.
        """
        path = f"/containers/{quote(container_id, safe='')}/json"
        response = self._request(method="GET", path=path, max_body_bytes=_MAX_CONTAINER_INSPECT_BYTES)
        if response.status != _HTTP_OK:
            message = f"Docker container inspection failed with HTTP {response.status}"
            raise DockerProtocolError(message)
        return json_object(self._json_body(response))

    def _create_execution(self, *, container_id: str, command: list[JsonValue]) -> str | ProbeExecution:
        container_path = quote(container_id, safe="")
        result = self._request(
            method="POST",
            path=f"/containers/{container_path}/exec",
            max_body_bytes=_MAX_EXEC_CONTROL_BYTES,
            body={
                "AttachStdout": True,
                "AttachStderr": True,
                "Tty": False,
                "Cmd": command,
            },
        )
        if result.status == _HTTP_NOT_FOUND:
            return ProbeExecution(None, b"", b"", "container_unavailable")
        if result.status != _HTTP_CREATED:
            return ProbeExecution(None, b"", b"", f"docker_exec_create_http_{result.status}")
        exec_id = text_value(json_object(self._json_body(result)).get("Id"))
        if not exec_id:
            message = "Docker exec creation omitted its id"
            raise DockerProtocolError(message)
        return exec_id

    def _start_execution(self, exec_id: str) -> tuple[bytes, bytes] | ProbeExecution:
        result = self._request(
            method="POST",
            path=f"/exec/{quote(exec_id, safe='')}/start",
            max_body_bytes=_MAX_EXEC_OUTPUT_BYTES,
            body={"Detach": False, "Tty": False},
        )
        if result.status != _HTTP_OK:
            return ProbeExecution(None, b"", b"", f"docker_exec_start_http_{result.status}")
        return decode_multiplexed_stream(result.body)

    def _inspect_execution(self, exec_id: str, *, stdout: bytes, stderr: bytes) -> ProbeExecution:
        result = self._request(
            method="GET",
            path=f"/exec/{quote(exec_id, safe='')}/json",
            max_body_bytes=_MAX_EXEC_CONTROL_BYTES,
        )
        if result.status != _HTTP_OK:
            return ProbeExecution(
                None,
                stdout,
                stderr,
                f"docker_exec_inspect_http_{result.status}",
            )
        exit_code = int_value(json_object(self._json_body(result)).get("ExitCode"))
        if exit_code is None:
            message = "Docker exec inspection omitted its exit code"
            raise DockerProtocolError(message)
        return ProbeExecution(exit_code, stdout, stderr, None)

    def execute_probe(self, *, container_id: str, command: list[JsonValue]) -> ProbeExecution:
        """Run one attached command with strictly bounded protocol output.

        Returns:
            The bounded command result and any explicit Docker protocol failure.

        """
        created = self._create_execution(container_id=container_id, command=command)
        if isinstance(created, ProbeExecution):
            return created
        started = self._start_execution(created)
        if isinstance(started, ProbeExecution):
            return started
        stdout, stderr = started
        return self._inspect_execution(created, stdout=stdout, stderr=stderr)
