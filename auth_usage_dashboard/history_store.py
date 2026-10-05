# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded private JSON store of redacted operational usage samples."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .history_values import isoformat, iterated_items, parse_datetime, sample_number, whole_number
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from datetime import datetime

    from .timeseries_types import JsonObject, JsonValue

SAMPLE_SCHEMA_VERSION = 1
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


class UsageSampleStore:
    """Bounded, redacted operational samples used for burn-rate estimation."""

    path: Path
    retention: timedelta
    sample_interval_seconds: int

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = 8,
        sample_interval_seconds: int = 300,
    ) -> None:
        """Configure the sample file, its retention window, and sample cadence."""
        self.path = path
        self.retention = timedelta(days=retention_days)
        self.sample_interval_seconds = sample_interval_seconds

    def read(self) -> list[JsonObject]:
        """Load every persisted sample after validating the store schema.

        Returns:
            Persisted samples in file order, or an empty list without a file.

        Raises:
            ValueError: If the schema, the sample list, or any sample is invalid.
        """
        if not self.path.exists():
            return []
        payload = cast("JsonValue", json.loads(self.path.read_text(encoding="utf-8")))
        if not isinstance(payload, dict) or payload.get("schema_version") != SAMPLE_SCHEMA_VERSION:
            message = "unsupported usage sample store schema"
            raise ValueError(message)
        stored_samples = payload.get("samples")
        samples = stored_samples if isinstance(stored_samples, list) else None
        if samples is None:
            message = "usage sample store is malformed"
            raise ValueError(message)
        validated: list[JsonObject] = []
        for sample in samples:
            valid_sample = _valid_sample(sample)
            if valid_sample is None:
                message = "usage sample store contains an invalid sample"
                raise ValueError(message)
            validated.append(valid_sample)
        return validated

    def record(self, accounts: list[JsonObject], *, at: datetime) -> list[JsonObject]:
        """Append one redacted sample when the configured cadence is due.

        Returns:
            The retained samples, including the new sample when one was written.
        """
        sampled_at = at.astimezone(UTC)
        cutoff = sampled_at - self.retention
        stored = self.read()
        samples = [sample for sample in stored if (parse_datetime(sample.get("at")) or sampled_at) >= cutoff]
        last_at = parse_datetime(samples[-1].get("at")) if samples else None
        if last_at is not None and (sampled_at - last_at).total_seconds() < self.sample_interval_seconds:
            return samples
        sampled_accounts: JsonObject = {}
        for account in accounts:
            label = account.get("label")
            if isinstance(label, str) and label:
                sampled_accounts[label] = _sample_account(account, at=sampled_at)
        samples.append({"at": isoformat(sampled_at), "accounts": sampled_accounts})
        self._write(samples)
        return samples

    def _write(self, samples: list[JsonObject]) -> None:
        self.path.parent.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        self.path.parent.chmod(_PRIVATE_DIRECTORY_MODE)
        encoded = json.dumps(
            {"schema_version": SAMPLE_SCHEMA_VERSION, "samples": samples},
            separators=(",", ":"),
            sort_keys=True,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        temporary = Path(temporary_name)
        try:
            _commit_sample_file(self.path, temporary=temporary, descriptor=descriptor, encoded=encoded)
        finally:
            temporary.unlink(missing_ok=True)


def _valid_sample(sample: JsonValue) -> JsonObject | None:
    if (
        isinstance(sample, dict)
        and parse_datetime(sample.get("at")) is not None
        and isinstance(sample.get("accounts"), dict)
    ):
        return sample
    return None


def _commit_sample_file(path: Path, *, temporary: Path, descriptor: int, encoded: str) -> None:
    os.fchmod(descriptor, _PRIVATE_FILE_MODE)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        _ = handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _ = temporary.replace(path)
    path.chmod(_PRIVATE_FILE_MODE)


def _sample_account(account: JsonObject, *, at: datetime) -> JsonObject:
    five_hour = optional_object(account.get("five_hour"))
    weekly = optional_object(account.get("weekly"))
    token_usage = optional_object(account.get("token_usage"))
    token_date = at.date().isoformat()
    today_tokens = _tokens_on(token_usage, token_date=token_date)
    return {
        "enabled": account.get("enabled") is True,
        "auth_valid": account.get("auth_valid") is True,
        "status": account.get("status"),
        "five_used_percent": sample_number(five_hour.get("used_percent")),
        "five_reset_at": five_hour.get("reset_at"),
        "weekly_used_percent": sample_number(weekly.get("used_percent")),
        "weekly_reset_at": weekly.get("reset_at"),
        "token_date": token_date,
        "tokens_today": today_tokens,
    }


def _tokens_on(token_usage: JsonObject, *, token_date: str) -> int:
    daily = iterated_items(token_usage.get("daily", []), description="token usage daily history")
    for point in daily:
        if isinstance(point, dict) and point.get("date") == token_date:
            return whole_number(point.get("tokens") or 0)
    return 0
