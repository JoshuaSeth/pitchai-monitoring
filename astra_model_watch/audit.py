# Copyright (c) 2026 PitchAI. All rights reserved.
"""Root-private append-only audit and alert-deduplication state."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

from .json_types import JsonObject, JsonValue, object_list, string_object_dict

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from .json_types import UntrustedValue

SENSITIVE_KEY_MARKERS = (
    "access_token",
    "refresh_token",
    "authorization",
    "id_token",
    "openai_api_key",
)


@final
class AuditError(RuntimeError):
    """A local evidence-store safety failure."""


def ensure_private_directory(path: Path) -> None:
    """Create a root-private directory and fail if its permissions are broad."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path_stat = path.lstat()
    unsafe_type = stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode)
    if unsafe_type or stat.S_IMODE(path_stat.st_mode) != 0o700:
        raise AuditError("audit_directory_must_be_mode_0700")


def _has_sensitive_key(value: JsonValue) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
                return True
            if _has_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_has_sensitive_key(item) for item in value)
    return False


@final
class AuditLog:
    """Append newline-delimited JSON with mode and secret checks."""

    def __init__(self, path: Path):
        ensure_private_directory(path.parent)
        self.path = path

    def append(
        self,
        event: JsonObject,
        *,
        sensitive_values: Sequence[str] = (),
    ) -> None:
        """Append one credential-free event and durably sync it to disk."""
        if _has_sensitive_key(event):
            raise AuditError("sensitive_key_refused")
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if any(value and value in line for value in sensitive_values):
            raise AuditError("sensitive_value_refused")
        flags = os.O_APPEND | os.O_CLOEXEC | os.O_CREAT | os.O_NOFOLLOW | os.O_WRONLY
        descriptor = os.open(self.path, flags, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            self._validate_descriptor(handle.fileno())
            _ = handle.write(f"{line}\n".encode())
            handle.flush()
            os.fsync(handle.fileno())

    def verify_permissions(self) -> None:
        """Verify an existing audit path remains a private regular file."""
        if not self.path.exists():
            return
        path_stat = self.path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise AuditError("audit_path_must_be_regular_file")
        if stat.S_IMODE(path_stat.st_mode) != 0o600:
            raise AuditError("audit_file_must_be_mode_0600")

    @staticmethod
    def _validate_descriptor(descriptor: int) -> None:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise AuditError("audit_path_must_be_regular_file")
        if stat.S_IMODE(file_stat.st_mode) != 0o600:
            raise AuditError("audit_file_must_be_mode_0600")


@final
class AlertState:
    """Persist hashed delivered-match keys so restarts cannot duplicate alerts."""

    def __init__(self, path: Path):
        ensure_private_directory(path.parent)
        self.path = path
        self._keys = self._load()

    def _load(self) -> set[str]:
        if not self.path.exists():
            return set()
        path_stat = self.path.lstat()
        unsafe_type = stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(
            path_stat.st_mode
        )
        if unsafe_type or stat.S_IMODE(path_stat.st_mode) != 0o600:
            raise AuditError("alert_state_file_must_be_regular_mode_0600")
        try:
            payload = cast("UntrustedValue", json.loads(self.path.read_bytes()))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise AuditError("invalid_alert_state") from None
        typed_payload = string_object_dict(payload)
        if typed_payload is None:
            raise AuditError("invalid_alert_state")
        raw_keys = object_list(typed_payload.get("delivered_match_keys"))
        if raw_keys is None or not all(isinstance(item, str) for item in raw_keys):
            raise AuditError("invalid_alert_state")
        return {item for item in raw_keys if isinstance(item, str)}

    def unseen(self, keys: Sequence[str]) -> list[str]:
        """Return match keys that have not been delivered successfully."""
        return [key for key in keys if key not in self._keys]

    def mark_delivered(self, keys: Sequence[str]) -> None:
        """Atomically persist newly delivered hashed match keys."""
        self._keys.update(keys)
        delivered_keys: list[JsonValue] = list(sorted(self._keys))
        payload: JsonObject = {"delivered_match_keys": delivered_keys}
        temporary_path = self._write_temporary_state(payload)
        try:
            _ = Path(temporary_path).replace(self.path)
        finally:
            self._unlink_if_exists(temporary_path)

    def _write_temporary_state(self, payload: JsonObject) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            delete=False,
        ) as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            _ = handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            return Path(handle.name)

    @staticmethod
    def _unlink_if_exists(path: Path) -> None:
        with suppress(FileNotFoundError):
            path.unlink()


@contextmanager
def exclusive_watch_lock(state_path: Path) -> Generator[None, None, None]:
    """Prevent concurrent monitors from duplicating requests and alerts."""
    ensure_private_directory(state_path.parent)
    lock_path = state_path.with_suffix(f"{state_path.suffix}.lock")
    descriptor = os.open(
        lock_path,
        os.O_CLOEXEC | os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    with ExitStack() as stack:
        _ = stack.callback(os.close, descriptor)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AuditError("another_astra_watch_is_running") from None
        _ = stack.callback(fcntl.flock, descriptor, fcntl.LOCK_UN)
        yield
