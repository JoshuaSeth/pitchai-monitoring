# Copyright (c) 2026 PitchAI. All rights reserved.
"""In-memory ASGI requests for isolated registry contracts, without a client socket."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.types import Message, Scope

    from .dashboard_records import Record


def multipart(fields: dict[str, str], filename: str, content: bytes, *,
              content_type: str = "text/plain") -> tuple[dict[str, str], bytes]:
    """Encode fixed synthetic form fields and one file without opening a network client.

    Returns:
        The multipart content header and exact body for the native ASGI request.
    """
    boundary = "registry-isolated-form-boundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.extend([
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(), content, f"\r\n--{boundary}--\r\n".encode(),
    ])
    return {"content-type": f"multipart/form-data; boundary={boundary}"}, b"".join(parts)


@dataclass
class Response:
    """Capture an ASGI response stream and signal its final body message."""

    status_code: int = 0
    body: bytes = b""
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    complete: asyncio.Event = field(default_factory=asyncio.Event)

    async def send(self, message: Message) -> None:
        """Consume the status/header message and ordered response-body chunks."""
        kind = cast("str", message["type"])
        if kind == "http.response.start":
            self.status_code = cast("int", message["status"])
            self.headers = cast("list[tuple[bytes, bytes]]", message.get("headers", []))
        elif kind == "http.response.body":
            self.body += cast("bytes", message.get("body", b""))
            if not message.get("more_body", False):
                self.complete.set()
        await asyncio.sleep(0)

    def json(self) -> Record:
        """Decode the object response expected by these HTTP contract tests.

        Returns:
            The JSON response object.
        """
        return cast("Record", json.loads(self.body))


async def request(
    application: FastAPI, path: str, *, method: str = "GET",
    headers: dict[str, str] | None = None, body: bytes = b"",
) -> Response:
    """Invoke one real ASGI HTTP scope without starting application lifespan.

    Returns:
        The captured response after the app has completed its request.
    """
    result = Response()
    parsed = urlsplit(path)
    encoded_headers: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        encoded_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope: Scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": method, "scheme": "https", "path": parsed.path,
        "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(), "root_path": "",
        "headers": encoded_headers, "client": ("fixture", 1), "server": ("fixture.invalid", 443),
    }
    submitted = False

    async def receive() -> Message:
        nonlocal submitted
        if not submitted:
            submitted = True
            return {"type": "http.request", "body": body, "more_body": False}
        await result.complete.wait()
        return {"type": "http.disconnect"}

    await application(scope, receive, result.send)
    return result
