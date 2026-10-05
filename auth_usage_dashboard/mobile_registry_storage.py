# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict private JSON storage for enrolled App Attest keys."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Never, cast

if TYPE_CHECKING:
    from .timeseries_types import JsonObject, JsonValue

type AppAttestEnvironment = Literal["development", "production"]


@dataclass
class RegisteredKey:
    """One enrolled public key and its monotonic assertion state."""

    public_key_pem: str
    receipt: str
    environment: AppAttestEnvironment
    registered_at: str
    last_counter: int = 0
    last_verified_at: str | None = None


def load_registry(path: Path) -> dict[str, RegisteredKey]:
    """Load and validate one registry file.

    Returns:
        Registered keys indexed by their Base64 identifiers.

    Registry structure violations fail loudly with ``RuntimeError``.
    """
    if not path.exists():
        return {}
    decoded = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
        _raise_registry_schema_error()
    raw_keys = decoded.get("keys")
    if not isinstance(raw_keys, dict):
        _raise_registry_schema_error()
    return {key_id: _parse_registered_key(value) for key_id, value in raw_keys.items()}


def persist_registry(path: Path, keys: dict[str, RegisteredKey]) -> None:
    """Atomically persist a registry with private directory and file modes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    encoded = json.dumps(
        _registry_payload(keys),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        _commit_registry_file(path, temporary, descriptor, encoded)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_registered_key(value: JsonValue) -> RegisteredKey:
    if not isinstance(value, dict):
        _raise_registry_schema_error()
    return RegisteredKey(
        public_key_pem=_required_text(value.get("public_key_pem")),
        receipt=_required_text(value.get("receipt")),
        environment=_required_environment(value.get("environment")),
        registered_at=_required_text(value.get("registered_at")),
        last_counter=_required_counter(value.get("last_counter")),
        last_verified_at=_optional_text(value.get("last_verified_at")),
    )


def _commit_registry_file(
    path: Path,
    temporary: Path,
    descriptor: int,
    encoded: bytes,
) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        _ = handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _ = temporary.replace(path)
    path.chmod(0o600)
    directory_descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _required_text(value: JsonValue) -> str:
    if not isinstance(value, str) or not value:
        _raise_registry_schema_error()
    return value


def _required_environment(value: JsonValue) -> AppAttestEnvironment:
    if value == "development":
        return "development"
    if value == "production":
        return "production"
    return _raise_registry_schema_error()


def _required_counter(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _raise_registry_schema_error()
    return value


def _optional_text(value: JsonValue) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return _raise_registry_schema_error()


def _registry_payload(keys: dict[str, RegisteredKey]) -> JsonObject:
    encoded_keys: JsonObject = {}
    for key_id, registered in keys.items():
        encoded_keys[key_id] = {
            "public_key_pem": registered.public_key_pem,
            "receipt": registered.receipt,
            "environment": registered.environment,
            "registered_at": registered.registered_at,
            "last_counter": registered.last_counter,
            "last_verified_at": registered.last_verified_at,
        }
    return {"schema_version": 1, "keys": encoded_keys}


def _raise_registry_schema_error() -> Never:
    message = "App Attest registry schema is invalid"
    raise RuntimeError(message)
