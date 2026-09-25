# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared lifecycle support for deterministic local HTTP test servers."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from http.server import BaseHTTPRequestHandler


class HttpVerbHandlerMixin:
    """Expose snake-case handlers through the verb names used by ``http.server``."""

    def handle_get(self) -> None:
        """Handle a GET request when implemented by a concrete test handler.

        Raises:
            NotImplementedError: The concrete handler did not implement GET.
        """
        raise NotImplementedError

    def handle_post(self) -> None:
        """Handle a POST request when implemented by a concrete test handler.

        Raises:
            NotImplementedError: The concrete handler did not implement POST.
        """
        raise NotImplementedError

    def __getattr__(self, name: str) -> Callable[[], None]:
        """Resolve the dynamic HTTP verb handler.

        Args:
            name: Missing attribute requested by ``BaseHTTPRequestHandler``.

        Returns:
            The matching snake-case handler.

        Raises:
            AttributeError: The requested attribute is not a supported HTTP verb.
        """
        if name == "do_GET":
            return self.handle_get
        if name == "do_POST":
            return self.handle_post
        raise AttributeError(name)


@contextmanager
def running_http_server(handler_class: type[BaseHTTPRequestHandler]) -> Generator[str]:
    """Run an HTTP handler on an ephemeral loopback port.

    Args:
        handler_class: Request-handler class to bind to the server.

    Yields:
        The base URL for the running server.
    """
    httpd = HTTPServer(("127.0.0.1", 0), handler_class)
    host = str(httpd.server_address[0])
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
