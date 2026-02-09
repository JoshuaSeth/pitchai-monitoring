from __future__ import annotations

import http.client
import json
import socket
from dataclasses import dataclass
from typing import Any


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:  # type: ignore[override]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


@dataclass(frozen=True)
class DockerUnixResponse:
    status: int
    ok: bool
    data: Any
    error: str | None


def docker_unix_get_json(*, socket_path: str, path: str, timeout_seconds: float = 5.0) -> DockerUnixResponse:
    """
    Minimal Docker Engine API client over /var/run/docker.sock.

    We intentionally avoid docker CLI and third-party libs inside the monitor container.
    """
    sp = str(socket_path or "").strip()
    if not sp:
        return DockerUnixResponse(status=0, ok=False, data=None, error="missing_socket_path")
    p = str(path or "").strip()
    if not p.startswith("/"):
        p = "/" + p

    conn: _UnixHTTPConnection | None = None
    try:
        conn = _UnixHTTPConnection(socket_path=sp, timeout=max(0.5, float(timeout_seconds)))
        conn.request("GET", p, headers={"Host": "docker"})
        resp = conn.getresponse()
        raw = resp.read()
        status = int(resp.status)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            data = raw.decode("utf-8", errors="replace")
        ok = 200 <= status < 300
        return DockerUnixResponse(status=status, ok=ok, data=data, error=None if ok else f"http_{status}")
    except FileNotFoundError:
        return DockerUnixResponse(status=0, ok=False, data=None, error="socket_not_found")
    except Exception as exc:
        return DockerUnixResponse(status=0, ok=False, data=None, error=f"{type(exc).__name__}: {exc}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
