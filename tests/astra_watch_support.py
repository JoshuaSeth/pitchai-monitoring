# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed fixtures for the ASTRA model-watch tests."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast, final

from astra_model_watch.catalog_transport import SAFE_TRANSPORT_CONTRACT
from astra_model_watch.json_types import JsonObject, string_object_dict

if TYPE_CHECKING:
    from astra_model_watch.json_types import UntrustedValue


@final
class RecordingTransport:
    """Record sanitized catalog calls and return a fixed payload."""

    def __init__(self, payload: JsonObject) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str], float]] = []

    @property
    def safety_contract(self) -> tuple[str, ...]:
        """Declare the same no-body synthetic transport policy."""
        return SAFE_TRANSPORT_CONTRACT

    def get_json(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> tuple[JsonObject, bool]:
        """Record one synthetic model-list request."""
        self.calls.append((url, dict(headers), timeout_seconds))
        return self.payload, True


@final
class RecordingNotifier:
    """Record notification preflights and messages without external writes."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.preflight_count = 0

    def preflight(self) -> JsonObject:
        """Record a synthetic private-route preflight."""
        self.preflight_count += 1
        return {
            "status": "ready",
            "policy": "personal-first",
            "route_kind": "private",
            "requester_key": "seth-ori",
        }

    def notify(self, message: str) -> JsonObject:
        """Record a synthetic requester-private message."""
        self.messages.append(message)
        return {
            "status": "sent",
            "policy": "personal-first",
            "route_kind": "private",
            "requester_key": "seth-ori",
        }


def jwt_for(account_id: str) -> str:
    """Return a synthetic unsigned JWT-shaped test value."""
    payload = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    return f"header.{encoded}.signature"


def make_account(
    root: Path,
    account_id: str,
    label: str,
    *,
    enabled: bool,
    token: str,
) -> None:
    """Write one synthetic broker account tree."""
    account_root = root / account_id
    account_root.mkdir(parents=True)
    _ = (account_root / "metadata.json").write_text(
        json.dumps({"account_id": account_id, "label": label, "enabled": enabled}),
    )
    _ = (account_root / "state.json").write_text(
        json.dumps({"availability": "available"}),
    )
    auth_path = account_root / "auth.json"
    _ = auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "id_token": jwt_for(account_id),
                    "access_token": token,
                    "refresh_token": "must-never-be-used",
                },
            },
        ),
    )
    auth_path.chmod(0o600)


def private_paths(root: Path) -> tuple[Path, Path, Path]:
    """Create a private account/log/state root."""
    private = root / "private"
    private.mkdir(mode=0o700)
    return private, private / "watch.jsonl", private / "alerts.json"


def events(path: Path) -> list[JsonObject]:
    """Load typed test events from an audit JSONL file."""
    loaded_events: list[JsonObject] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw_event = cast("UntrustedValue", json.loads(line))
        event = string_object_dict(raw_event)
        if event is None:
            message = "test audit event was not a JSON object"
            raise ValueError(message)
        loaded_events.append(event)
    return loaded_events


@contextmanager
def temporary_path() -> Generator[Path, None, None]:
    """Yield an isolated filesystem root without relying on pytest typing."""
    with TemporaryDirectory() as directory:
        yield Path(directory)
