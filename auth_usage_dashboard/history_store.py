# Copyright (c) 2026 PitchAI. All rights reserved.
"""Persist bounded redacted dashboard capacity samples."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .json_contract import decode_document
from .value_parsing import UTC, integer, isoformat, number, parse_datetime

if TYPE_CHECKING:
    from datetime import datetime

    from .json_contract import JsonObject, JsonValue
    from .models import CapacityAccount, UsageSample, UsageSampleAccount

SAMPLE_SCHEMA_VERSION = 1


class UsageSampleFormatError(ValueError):
    """A persisted usage sample violated the storage schema."""


class UsageSampleStore:
    """Bounded, redacted operational samples used for burn-rate estimation."""

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = 8,
        sample_interval_seconds: int = 300,
    ) -> None:
        """Initialize this instance."""
        self.path: Path = path
        self.retention: timedelta = timedelta(days=retention_days)
        self.sample_interval_seconds: int = sample_interval_seconds

    def read(self) -> list[UsageSample]:
        """Read and validate every persisted usage sample.

        Returns:
            The resulting collection.

        Raises:
            UsageSampleFormatError: If persisted samples violate the storage schema.

        """
        if not self.path.exists():
            return []
        payload = decode_document(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SAMPLE_SCHEMA_VERSION:
            msg = "unsupported usage sample store schema"
            raise UsageSampleFormatError(msg)
        samples = payload.get("samples")
        if not isinstance(samples, list):
            msg = "usage sample store is malformed"
            raise UsageSampleFormatError(msg)
        return [_parse_sample(sample) for sample in samples]

    def record(
        self,
        accounts: list[CapacityAccount],
        *,
        at: datetime,
    ) -> list[UsageSample]:
        """Append a redacted sample when the configured interval elapsed.

        Returns:
            The resulting collection.

        """
        at = at.astimezone(UTC)
        samples = self.read()
        cutoff = at - self.retention
        retained: list[UsageSample] = [sample for sample in samples if (sample_at(sample) or at) >= cutoff]
        last_at = sample_at(retained[-1]) if retained else None
        if last_at is not None and (at - last_at).total_seconds() < self.sample_interval_seconds:
            return retained
        sampled_accounts: dict[str, UsageSampleAccount] = {}
        for account in accounts:
            label = account["label"]
            if label:
                sampled_accounts[label] = _sample_account(account, at=at)
        retained.append({"at": isoformat(at), "accounts": sampled_accounts})
        self._write(retained)
        return retained

    def _write(self, samples: list[UsageSample]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        Path(self.path.parent).chmod(0o700)
        payload = {"schema_version": SAMPLE_SCHEMA_VERSION, "samples": samples}
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        try:
            _publish_sample_file(descriptor, temporary_name, self.path, encoded)
        except (OSError, ValueError, TypeError):
            _remove_temporary_file(Path(temporary_name))
            raise


def _remove_temporary_file(path: Path) -> bool:
    """Remove a failed write artifact when it still exists.

    Returns:
        Whether an artifact existed and was removed.

    """
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _publish_sample_file(
    descriptor: int,
    temporary_name: str,
    destination: Path,
    encoded: str,
) -> None:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        _ = handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _ = Path(temporary_name).replace(destination)
    Path(destination).chmod(0o600)


def _sample_account(account: CapacityAccount, *, at: datetime) -> UsageSampleAccount:
    five_hour = account["five_hour"]
    weekly = account["weekly"]
    token_usage = account["token_usage"]
    token_date = at.date().isoformat()
    today_tokens = 0
    for point in token_usage.get("daily", []):
        if point["date"] == token_date:
            today_tokens = point["tokens"]
            break
    return {
        "enabled": account.get("enabled") is True,
        "auth_valid": account.get("auth_valid") is True,
        "status": account.get("status"),
        "five_used_percent": number(five_hour.get("used_percent")),
        "five_reset_at": five_hour.get("reset_at"),
        "weekly_used_percent": number(weekly.get("used_percent")),
        "weekly_reset_at": weekly.get("reset_at"),
        "token_date": token_date,
        "tokens_today": today_tokens,
    }


def _parse_sample(value: JsonValue) -> UsageSample:
    """Validate and normalize one persisted usage sample.

    Returns:
        The resulting value.

    Raises:
        UsageSampleFormatError: If one sample violates the storage schema.

    """
    if not isinstance(value, dict):
        msg = "usage sample store contains a non-object sample"
        raise UsageSampleFormatError(msg)
    at = value.get("at")
    if not isinstance(at, str) or parse_datetime(at) is None:
        msg = "usage sample store contains an invalid sample timestamp"
        raise UsageSampleFormatError(msg)
    raw_accounts = value.get("accounts")
    if not isinstance(raw_accounts, dict):
        msg = "usage sample store contains invalid accounts"
        raise UsageSampleFormatError(msg)
    accounts: dict[str, UsageSampleAccount] = {}
    for label, raw_account in raw_accounts.items():
        if not isinstance(raw_account, dict):
            msg = "usage sample store contains a non-object account"
            raise UsageSampleFormatError(msg)
        accounts[label] = _parse_sample_account(raw_account)
    return {"at": at, "accounts": accounts}


def _parse_sample_account(raw: JsonObject) -> UsageSampleAccount:
    status = raw.get("status")
    token_date = raw.get("token_date")
    five_reset_at = raw.get("five_reset_at")
    weekly_reset_at = raw.get("weekly_reset_at")
    return {
        "enabled": raw.get("enabled") is True,
        "auth_valid": raw.get("auth_valid") is True,
        "status": status if isinstance(status, str) else None,
        "five_used_percent": number(raw.get("five_used_percent")),
        "five_reset_at": five_reset_at if isinstance(five_reset_at, str) else None,
        "weekly_used_percent": number(raw.get("weekly_used_percent")),
        "weekly_reset_at": weekly_reset_at if isinstance(weekly_reset_at, str) else None,
        "token_date": token_date if isinstance(token_date, str) else "",
        "tokens_today": integer(raw.get("tokens_today")) or 0,
    }


def sample_at(sample: UsageSample) -> datetime | None:
    """Return the parsed timestamp for one sample."""
    return parse_datetime(sample.get("at"))
