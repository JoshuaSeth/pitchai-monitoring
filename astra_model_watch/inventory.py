# Copyright (c) 2026 PitchAI. All rights reserved.
"""Load broker accounts without mutating or refreshing authentication state."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast, final

from .json_types import JsonObject, JsonValue, string_object_dict
from .types import BrokerAccount, BrokerAuthentication

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import UntrustedValue

MAX_ACCOUNT_FILE_BYTES = 1024 * 1024
AUTH_CLAIM_KEY = "https://api.openai.com/auth"


@final
class InventoryError(RuntimeError):
    """A sanitized broker-inventory failure."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class AccountPresentation:
    """Non-secret account label and broker scheduling state."""

    label: str
    enabled: bool
    availability: str


def _regular_file_stat(path: Path) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        raise InventoryError(f"missing_{path.name}") from None
    except PermissionError:
        raise InventoryError(f"unreadable_{path.name}") from None
    except OSError:
        raise InventoryError(f"read_failed_{path.name}") from None
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise InventoryError(f"unsafe_{path.name}_file_type")
    return path_stat


def _bounded_read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read(MAX_ACCOUNT_FILE_BYTES + 1)


def _read_json_object(path: Path) -> JsonObject:
    _ = _regular_file_stat(path)
    try:
        raw = _bounded_read(path)
    except PermissionError:
        raise InventoryError(f"unreadable_{path.name}") from None
    except OSError:
        raise InventoryError(f"read_failed_{path.name}") from None
    if len(raw) > MAX_ACCOUNT_FILE_BYTES:
        raise InventoryError(f"oversize_{path.name}")
    try:
        payload = cast("UntrustedValue", json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InventoryError(f"invalid_{path.name}") from None
    typed_payload = string_object_dict(payload)
    if typed_payload is None:
        raise InventoryError(f"invalid_{path.name}")
    return typed_payload


def _safe_text(value: JsonValue, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split())[:160]
    return cleaned or fallback


def _decode_jwt_payload(token: str) -> JsonObject:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    segment = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        encoded = segment.encode("ascii")
    except UnicodeEncodeError:
        return {}
    try:
        decoded = base64.urlsafe_b64decode(encoded)
    except ValueError:
        return {}
    try:
        payload = cast("UntrustedValue", json.loads(decoded))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return string_object_dict(payload) or {}


def _account_identity(tokens: JsonObject) -> tuple[str | None, str | None]:
    for token_field in ("id_token", "access_token"):
        token = tokens.get(token_field)
        if not isinstance(token, str) or not token.strip():
            continue
        payload = _decode_jwt_payload(token)
        auth_claims = string_object_dict(payload.get(AUTH_CLAIM_KEY)) or {}
        candidates = (
            (auth_claims.get("chatgpt_account_id"), f"{token_field}.signed_auth_claim"),
            (
                payload.get("chatgpt_account_id"),
                f"{token_field}.signed_top_level_claim",
            ),
            (payload.get("account_id"), f"{token_field}.signed_account_claim"),
        )
        for candidate, source in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip(), source
    explicit = tokens.get("account_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), "tokens.account_id_fallback"
    return None, None


def _file_facts(path: Path) -> tuple[str | None, str | None]:
    try:
        path_stat = path.stat(follow_symlinks=False)
    except OSError:
        return None, None
    mode = stat.S_IMODE(path_stat.st_mode)
    mtime = datetime.fromtimestamp(path_stat.st_mtime, timezone.utc).isoformat()
    return f"{mode:04o}", mtime


def _presentation(root: Path) -> AccountPresentation:
    metadata = _read_json_object(root / "metadata.json")
    state = _read_json_object(root / "state.json")
    metadata_id = metadata.get("account_id")
    if not isinstance(metadata_id, str) or metadata_id != root.name:
        raise InventoryError("metadata_account_id_mismatch")
    return AccountPresentation(
        label=_safe_text(metadata.get("label"), root.name),
        enabled=metadata.get("enabled", True) is not False,
        availability=_safe_text(state.get("availability"), "unknown"),
    )


def _authentication(
    root: Path,
    mode: str | None,
    mtime: str | None,
) -> BrokerAuthentication:
    auth_path = root / "auth.json"
    if mode != "0600":
        raise InventoryError("unsafe_auth_file_mode")
    auth_payload = _read_json_object(auth_path)
    tokens = string_object_dict(auth_payload.get("tokens"))
    if tokens is None:
        raise InventoryError("missing_auth_tokens")
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise InventoryError("missing_access_token")
    account_header_id, account_id_source = _account_identity(tokens)
    if account_header_id != root.name:
        raise InventoryError("auth_account_id_mismatch")
    return BrokerAuthentication(
        auth_path=auth_path,
        auth_file_mode=mode,
        auth_file_mtime_utc=mtime,
        access_token=access_token.strip(),
        account_header_id=account_header_id,
        account_id_source=account_id_source,
    )


def _validated_account(
    root: Path,
    fingerprint: str,
    mode: str | None,
    mtime: str | None,
) -> BrokerAccount:
    presentation = _presentation(root)
    return BrokerAccount(
        directory_name=root.name,
        label=presentation.label,
        enabled=presentation.enabled,
        availability=presentation.availability,
        fingerprint=fingerprint,
        authentication=_authentication(root, mode, mtime),
    )


def _load_account(root: Path) -> BrokerAccount:
    auth_path = root / "auth.json"
    fingerprint = hashlib.sha256(root.name.encode()).hexdigest()[:16]
    mode, mtime = _file_facts(auth_path)
    try:
        return _validated_account(root, fingerprint, mode, mtime)
    except InventoryError as exc:
        return BrokerAccount(
            directory_name=root.name,
            label=root.name,
            enabled=False,
            availability="unknown",
            fingerprint=fingerprint,
            authentication=BrokerAuthentication(
                auth_path=auth_path,
                auth_file_mode=mode,
                auth_file_mtime_utc=mtime,
                access_token=None,
                account_header_id=None,
                error_code=exc.error_code,
            ),
        )


def load_broker_accounts(accounts_dir: Path) -> list[BrokerAccount]:
    """Return every directory-backed broker account in deterministic order."""
    try:
        directory_stat = accounts_dir.stat()
    except OSError:
        raise InventoryError("accounts_directory_unavailable") from None
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise InventoryError("accounts_directory_unavailable")
    try:
        roots = sorted(
            path
            for path in accounts_dir.iterdir()
            if path.is_dir() and not path.is_symlink()
        )
    except OSError:
        raise InventoryError("accounts_directory_unreadable") from None
    if not roots:
        raise InventoryError("account_inventory_empty")
    return [_load_account(root) for root in roots]
