from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc
SAMPLE_SCHEMA_VERSION = 1
HISTORY_HOURS = 7 * 24


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def floor_hour(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


class UsageSampleStore:
    """Bounded, redacted operational samples used for burn-rate estimation."""

    def __init__(
        self,
        path: Path,
        *,
        retention_days: int = 8,
        sample_interval_seconds: int = 300,
    ) -> None:
        self.path = path
        self.retention = timedelta(days=retention_days)
        self.sample_interval_seconds = sample_interval_seconds

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SAMPLE_SCHEMA_VERSION:
            raise ValueError("unsupported usage sample store schema")
        samples = payload.get("samples")
        if not isinstance(samples, list):
            raise ValueError("usage sample store is malformed")
        if any(not _valid_sample(sample) for sample in samples):
            raise ValueError("usage sample store contains an invalid sample")
        return samples

    def record(self, accounts: list[dict[str, Any]], *, at: datetime) -> list[dict[str, Any]]:
        at = at.astimezone(UTC)
        samples = self.read()
        cutoff = at - self.retention
        samples = [sample for sample in samples if (_sample_at(sample) or at) >= cutoff]
        last_at = _sample_at(samples[-1]) if samples else None
        if last_at is not None and (at - last_at).total_seconds() < self.sample_interval_seconds:
            return samples

        sampled_accounts: dict[str, dict[str, Any]] = {}
        for account in accounts:
            label = account.get("label")
            if not isinstance(label, str) or not label:
                continue
            sampled_accounts[label] = _sample_account(account, at=at)
        samples.append({"at": isoformat(at), "accounts": sampled_accounts})
        self._write(samples)
        return samples

    def _write(self, samples: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        payload = {"schema_version": SAMPLE_SCHEMA_VERSION, "samples": samples}
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def build_hourly_usage_history(
    accounts: list[dict[str, Any]],
    *,
    samples: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    now = now.astimezone(UTC)
    end = floor_hour(now)
    start = end - timedelta(hours=HISTORY_HOURS - 1)
    hours = [start + timedelta(hours=offset) for offset in range(HISTORY_HOURS)]
    reporting = [account for account in accounts if account["token_usage"]["available"]]
    observed = _observed_token_deltas(samples, start=start, end=now)
    series: list[dict[str, Any]] = []

    for account in reporting:
        daily_totals = {
            point["date"]: int(point["tokens"])
            for point in account["token_usage"]["daily"]
        }
        points = _hourly_points(
            hours,
            daily_totals=daily_totals,
            observed=observed.get(account["label"], {}),
            now=now,
        )
        series.append(
            {
                "label": account["label"],
                "points": points,
                "updated_at": account["token_usage"]["updated_at"],
                "stale": account["token_usage"]["stale"],
                "native_hour_count": sum(1 for point in points if point["observed_tokens"] > 0),
            }
        )
    series.sort(key=lambda item: item["label"].lower())

    combined: list[dict[str, Any]] = []
    for index, at in enumerate(hours):
        raw_tokens = sum(item["points"][index]["tokens"] for item in series)
        observed_tokens = sum(item["points"][index]["observed_tokens"] for item in series)
        combined.append(
            {
                "at": isoformat(at),
                "tokens": raw_tokens,
                "observed_tokens": observed_tokens,
                "reconstructed_tokens": max(0, raw_tokens - observed_tokens),
                "provenance": _provenance(raw_tokens, observed_tokens),
                "accounts_reporting": len(reporting),
            }
        )
    _add_smoothed_values(combined)
    for item in series:
        _add_smoothed_values(item["points"])

    values = [point["tokens"] for point in combined]
    observed_total = sum(point["observed_tokens"] for point in combined)
    total = sum(values)
    updated_values = [
        parse_datetime(account["token_usage"].get("updated_at"))
        for account in reporting
    ]
    valid_updates = [value for value in updated_values if value is not None]
    return {
        "granularity": "hour",
        "provider_granularity": "daily",
        "timezone": "UTC",
        "period_start": isoformat(start),
        "period_end": isoformat(now),
        "point_count": len(combined),
        "current_hour_partial": True,
        "accounts_reporting": len(reporting),
        "configured_accounts": len(accounts),
        "stale_account_count": sum(1 for account in reporting if account["token_usage"]["stale"]),
        "updated_at": isoformat(min(valid_updates)) if valid_updates else None,
        "combined": combined,
        "series": series,
        "summary": {
            "seven_day_tokens": total,
            "average_hourly_tokens": round(total / len(combined)) if combined else 0,
            "peak_hourly_tokens": max(values, default=0),
            "trailing_two_hour_tokens": sum(values[-2:]),
            "observed_share_percent": round(observed_total / total * 100.0, 1) if total else 0.0,
        },
        "reconstruction": {
            "method": "daily-total-constrained hourly allocation with three-hour smoothing",
            "daily_totals_preserved": True,
            "native_samples_used": observed_total > 0,
            "native_hour_count": sum(1 for point in combined if point["observed_tokens"] > 0),
            "estimated_hour_count": sum(1 for point in combined if point["reconstructed_tokens"] > 0),
            "note": "Provider history is daily. Hourly estimates preserve reported daily totals and are replaced by observed sample deltas as coverage accumulates.",
        },
    }


def capacity_burn_rate(
    accounts: list[dict[str, Any]],
    *,
    samples: list[dict[str, Any]],
    now: datetime,
    lookback_hours: int = 2,
) -> dict[str, Any]:
    now = now.astimezone(UTC)
    cutoff = now - timedelta(hours=lookback_hours)
    rates: list[float] = []
    sampled_points = 0.0
    sampled_hours = 0.0
    covered_labels: set[str] = set()
    recent = [sample for sample in samples if (_sample_at(sample) or now) >= cutoff - timedelta(minutes=15)]

    for previous, current in zip(recent, recent[1:]):
        previous_at = _sample_at(previous)
        current_at = _sample_at(current)
        if previous_at is None or current_at is None or current_at <= previous_at or current_at < cutoff:
            continue
        hours = (current_at - max(previous_at, cutoff)).total_seconds() / 3600.0
        if hours <= 0:
            continue
        previous_accounts = previous.get("accounts", {})
        current_accounts = current.get("accounts", {})
        interval_points = 0.0
        interval_covered = False
        for label, current_account in current_accounts.items():
            previous_account = previous_accounts.get(label)
            if not isinstance(previous_account, dict) or not isinstance(current_account, dict):
                continue
            if previous_account.get("five_reset_at") != current_account.get("five_reset_at"):
                continue
            previous_used = _number(previous_account.get("five_used_percent"))
            current_used = _number(current_account.get("five_used_percent"))
            if previous_used is None or current_used is None or current_used < previous_used:
                continue
            interval_points += current_used - previous_used
            covered_labels.add(label)
            interval_covered = True
        if interval_covered:
            rates.append(interval_points / hours)
            sampled_points += interval_points
            sampled_hours += hours

    native_rate = sampled_points / sampled_hours if sampled_hours > 0 else None
    fallback_rates = _current_window_rates(accounts, now=now)
    if native_rate is not None and len(recent) >= 3:
        rate = native_rate
        source = "native_broker_samples"
        confidence = "high" if len(recent) >= 9 and len(covered_labels) >= 2 else "medium"
    else:
        rate = sum(fallback_rates)
        source = "current_window_average"
        confidence = "medium" if len(fallback_rates) >= 2 else "low"

    variation = _coefficient_of_variation(rates)
    if variation is None:
        variation = 0.4 if confidence == "medium" else 0.65
    return {
        "capacity_points_per_hour": round(max(0.0, rate), 2),
        "source": source,
        "lookback_hours": lookback_hours if source == "native_broker_samples" else None,
        "fallback_window": "current five-hour windows" if source != "native_broker_samples" else None,
        "confidence": confidence,
        "sample_count": len(recent),
        "covered_accounts": len(covered_labels) if source == "native_broker_samples" else len(fallback_rates),
        "coefficient_of_variation": round(min(1.5, max(0.15, variation)), 3),
        "native_interval_rates": [round(value, 3) for value in rates[-24:]],
    }


def _sample_account(account: dict[str, Any], *, at: datetime) -> dict[str, Any]:
    five_hour = account.get("five_hour") if isinstance(account.get("five_hour"), dict) else {}
    weekly = account.get("weekly") if isinstance(account.get("weekly"), dict) else {}
    token_usage = account.get("token_usage") if isinstance(account.get("token_usage"), dict) else {}
    token_date = at.date().isoformat()
    today_tokens = 0
    for point in token_usage.get("daily", []):
        if isinstance(point, dict) and point.get("date") == token_date:
            today_tokens = int(point.get("tokens") or 0)
            break
    return {
        "enabled": account.get("enabled") is True,
        "auth_valid": account.get("auth_valid") is True,
        "status": account.get("status"),
        "five_used_percent": _number(five_hour.get("used_percent")),
        "five_reset_at": five_hour.get("reset_at"),
        "weekly_used_percent": _number(weekly.get("used_percent")),
        "weekly_reset_at": weekly.get("reset_at"),
        "token_date": token_date,
        "tokens_today": today_tokens,
    }


def _valid_sample(sample: Any) -> bool:
    return (
        isinstance(sample, dict)
        and _sample_at(sample) is not None
        and isinstance(sample.get("accounts"), dict)
    )


def _sample_at(sample: dict[str, Any]) -> datetime | None:
    return parse_datetime(sample.get("at"))


def _observed_token_deltas(
    samples: list[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, dict[datetime, int]]:
    observed: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    ordered = sorted(samples, key=lambda sample: sample.get("at", ""))
    for previous, current in zip(ordered, ordered[1:]):
        current_at = _sample_at(current)
        if current_at is None or current_at < start or current_at > end:
            continue
        previous_accounts = previous.get("accounts", {})
        current_accounts = current.get("accounts", {})
        for label, current_account in current_accounts.items():
            previous_account = previous_accounts.get(label)
            if not isinstance(previous_account, dict) or not isinstance(current_account, dict):
                continue
            if previous_account.get("token_date") != current_account.get("token_date"):
                continue
            previous_total = _integer(previous_account.get("tokens_today"))
            current_total = _integer(current_account.get("tokens_today"))
            if previous_total is None or current_total is None or current_total <= previous_total:
                continue
            observed[label][floor_hour(current_at)] += current_total - previous_total
    return {label: dict(values) for label, values in observed.items()}


def _hourly_points(
    hours: list[datetime],
    *,
    daily_totals: dict[str, int],
    observed: dict[datetime, int],
    now: datetime,
) -> list[dict[str, Any]]:
    allocations: dict[datetime, tuple[int, int]] = {}
    dates = sorted({hour.date() for hour in hours})
    for day in dates:
        total = int(daily_totals.get(day.isoformat(), 0))
        if total <= 0:
            continue
        active_hours = [
            datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
            for hour in range(24)
            if day < now.date() or hour <= now.hour
        ]
        observed_for_day = {
            hour: value
            for hour, value in observed.items()
            if hour.date() == day and hour in active_hours and value > 0
        }
        observed_values = _bounded_observed(observed_for_day, total=total)
        observed_total = sum(observed_values.values())
        reconstructed = _distribute_integer(total - observed_total, active_hours)
        for hour in active_hours:
            allocations[hour] = (
                reconstructed.get(hour, 0) + observed_values.get(hour, 0),
                observed_values.get(hour, 0),
            )

    points: list[dict[str, Any]] = []
    for hour in hours:
        tokens, observed_tokens = allocations.get(hour, (0, 0))
        points.append(
            {
                "at": isoformat(hour),
                "tokens": tokens,
                "observed_tokens": observed_tokens,
                "reconstructed_tokens": max(0, tokens - observed_tokens),
                "provenance": _provenance(tokens, observed_tokens),
            }
        )
    return points


def _bounded_observed(values: dict[datetime, int], *, total: int) -> dict[datetime, int]:
    observed_total = sum(values.values())
    if observed_total <= total:
        return values
    if observed_total <= 0:
        return {}
    weights = {hour: value / observed_total for hour, value in values.items()}
    return _distribute_weighted(total, weights)


def _distribute_integer(total: int, keys: list[datetime]) -> dict[datetime, int]:
    if total <= 0 or not keys:
        return {key: 0 for key in keys}
    base, remainder = divmod(total, len(keys))
    return {key: base + (1 if index < remainder else 0) for index, key in enumerate(keys)}


def _distribute_weighted(total: int, weights: dict[datetime, float]) -> dict[datetime, int]:
    raw = {key: total * weight for key, weight in weights.items()}
    result = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = total - sum(result.values())
    order = sorted(raw, key=lambda key: raw[key] - result[key], reverse=True)
    for key in order[:remainder]:
        result[key] += 1
    return result


def _add_smoothed_values(points: list[dict[str, Any]]) -> None:
    values = [float(point.get("tokens") or 0) for point in points]
    weights = (1, 2, 3, 2, 1)
    for index, point in enumerate(points):
        weighted = 0.0
        divisor = 0
        for offset, weight in zip(range(-2, 3), weights):
            candidate = index + offset
            if 0 <= candidate < len(values):
                weighted += values[candidate] * weight
                divisor += weight
        point["smoothed_tokens"] = round(weighted / divisor) if divisor else 0


def _provenance(tokens: int, observed_tokens: int) -> str:
    if observed_tokens <= 0:
        return "reconstructed" if tokens > 0 else "none"
    return "observed" if observed_tokens >= tokens else "blended"


def _current_window_rates(accounts: list[dict[str, Any]], *, now: datetime) -> list[float]:
    rates: list[float] = []
    for account in accounts:
        if not account.get("enabled") or account.get("auth_valid") is not True or account.get("stale"):
            continue
        window = account.get("five_hour") if isinstance(account.get("five_hour"), dict) else {}
        used = _number(window.get("used_percent"))
        reset_at = parse_datetime(window.get("reset_at"))
        window_seconds = _integer(window.get("window_seconds")) or 18_000
        if used is None or reset_at is None:
            continue
        started_at = reset_at - timedelta(seconds=window_seconds)
        elapsed_hours = (now - started_at).total_seconds() / 3600.0
        if 1 / 12 <= elapsed_hours <= window_seconds / 3600.0 + 0.25:
            rates.append(max(0.0, used / elapsed_hours))
    return rates


def _coefficient_of_variation(values: list[float]) -> float | None:
    positive = [value for value in values if value >= 0]
    if len(positive) < 3:
        return None
    mean = sum(positive) / len(positive)
    if mean <= 0:
        return None
    variance = sum((value - mean) ** 2 for value in positive) / (len(positive) - 1)
    return math.sqrt(variance) / mean


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
