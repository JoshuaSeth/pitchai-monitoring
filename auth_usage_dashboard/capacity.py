from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc
FORECAST_HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_account(
    raw: dict[str, Any],
    *,
    now: datetime,
    stale_after_seconds: int,
    min_five_hour_remaining_percent: float,
    probe_error: str | None = None,
) -> dict[str, Any]:
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    state = raw.get("state") if isinstance(raw.get("state"), dict) else {}
    usage = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    rate_limit = usage.get("rate_limit") if isinstance(usage.get("rate_limit"), dict) else {}

    label = _string(metadata.get("label")) or "Unlabeled account"
    email = _string(usage.get("email")) or label
    enabled = metadata.get("enabled", True) is not False
    availability = _string(state.get("availability")) or "unknown"
    five_hour = _parse_window(rate_limit.get("primary_window"), now=now, default_seconds=18_000)
    weekly = _parse_window(rate_limit.get("secondary_window"), now=now, default_seconds=604_800)
    last_probe = _parse_datetime(state.get("last_probe_at"))
    stale_seconds = None if last_probe is None else max(0, int((now - last_probe).total_seconds()))
    stale = last_probe is None or stale_seconds > stale_after_seconds

    five_remaining = five_hour.get("remaining_percent")
    weekly_remaining = weekly.get("remaining_percent")
    primary_reset_at = _parse_datetime(five_hour.get("reset_at"))
    weekly_reset_at = _parse_datetime(weekly.get("reset_at"))
    primary_reset_due = primary_reset_at is not None and primary_reset_at <= now
    weekly_reset_due = weekly_reset_at is not None and weekly_reset_at <= now
    at_safety_floor = (
        availability == "available"
        and five_remaining is not None
        and five_remaining <= min_five_hour_remaining_percent
    )

    if not enabled:
        status = "disabled"
        reason = "Disabled in broker inventory"
    elif availability == "auth_invalid":
        status = "auth_invalid"
        reason = "Login or token refresh required"
    elif not usage or availability == "unknown":
        status = "unknown"
        reason = "Usage state unavailable"
    elif weekly_remaining is not None and weekly_remaining <= 0 and not weekly_reset_due:
        status = "weekly_limited"
        reason = "Weekly usage window exhausted"
    elif five_remaining is not None and five_remaining <= 0 and not primary_reset_due:
        status = "five_hour_limited"
        reason = "Five-hour usage window exhausted"
    elif at_safety_floor:
        status = "five_hour_limited"
        reason = "Held at broker five-hour safety floor"
    elif availability == "rate_limited":
        status = "unknown" if primary_reset_due or weekly_reset_due else "five_hour_limited"
        reason = "Reset is due; awaiting a fresh provider state" if status == "unknown" else "Usage limited"
    elif availability == "available":
        status = "available"
        reason = "Selectable now"
    else:
        status = "unknown"
        reason = "Unrecognized broker availability"

    if availability == "auth_invalid":
        auth_valid: bool | None = False
    elif availability in {"available", "rate_limited"} or usage:
        auth_valid = True
    else:
        auth_valid = None

    credits = _parse_reset_credits(usage.get("rate_limit_reset_credits"))
    active_sessions = _integer(state.get("active_session_count"), minimum=0) or 0

    return {
        "label": label,
        "email": email,
        "enabled": enabled,
        "plan_type": _string(usage.get("plan_type")),
        "status": status,
        "status_reason": reason,
        "availability": availability,
        "auth_valid": auth_valid,
        "selectable_now": status == "available",
        "selection_blocked": status != "available",
        "safety_floor_active": at_safety_floor,
        "five_hour": five_hour,
        "weekly": weekly,
        "reset_credits": credits,
        "active_session_count": active_sessions,
        "latest_session_expires_at": isoformat(_parse_datetime(state.get("lease_expires_at"))),
        "last_probe_at": isoformat(last_probe),
        "stale": stale,
        "stale_seconds": stale_seconds,
        "probe_error": probe_error,
    }


def build_dashboard_snapshot(
    raw_accounts: list[dict[str, Any]],
    *,
    now: datetime,
    stale_after_seconds: int,
    min_five_hour_remaining_percent: float,
    probe_errors: dict[str, str] | None = None,
    source_error: str | None = None,
    last_safe_probe_at: datetime | None = None,
    probe_interval_seconds: int = 300,
) -> dict[str, Any]:
    probe_errors = probe_errors or {}
    accounts = [
        parse_account(
            raw,
            now=now,
            stale_after_seconds=stale_after_seconds,
            min_five_hour_remaining_percent=min_five_hour_remaining_percent,
            probe_error=probe_errors.get(
                str((raw.get("metadata") or {}).get("label") or (raw.get("metadata") or {}).get("account_id") or "")
            ),
        )
        for raw in raw_accounts
    ]
    accounts.sort(key=lambda account: (not account["enabled"], account["email"].lower()))

    forecasts = [
        _forecast(accounts, now=now, key=key, label=label, horizon_seconds=seconds)
        for key, label, seconds in FORECAST_HORIZONS
    ]
    warnings = _warnings(accounts, source_error=source_error, probe_errors=probe_errors)
    events = _capacity_events(accounts, now=now, horizon_seconds=24 * 60 * 60)
    status_counts = {
        status: sum(1 for account in accounts if account["status"] == status)
        for status in ("available", "five_hour_limited", "weekly_limited", "auth_invalid", "disabled", "unknown")
    }
    last_probe_values = [
        _parse_datetime(account.get("last_probe_at")) for account in accounts if account.get("last_probe_at")
    ]
    oldest_probe = min((value for value in last_probe_values if value is not None), default=None)
    newest_probe = max((value for value in last_probe_values if value is not None), default=None)
    enabled_accounts = [account for account in accounts if account["enabled"]]
    stale_count = sum(1 for account in enabled_accounts if account["stale"])
    fresh_usable_count = sum(
        1 for account in enabled_accounts if account["selectable_now"] and not account["stale"]
    )
    next_useful = next((event for event in events if event["kind"] in {"five_hour_reset", "weekly_reset"}), None)

    return {
        "schema_version": 1,
        "generated_at": isoformat(now),
        "source": {
            "name": "authoritative Codex authentication broker",
            "mode": "read-only state files plus no-generation usage probes",
            "probe_interval_seconds": probe_interval_seconds,
            "last_safe_probe_at": isoformat(last_safe_probe_at),
            "oldest_account_probe_at": isoformat(oldest_probe),
            "newest_account_probe_at": isoformat(newest_probe),
            "stale": bool(source_error or stale_count),
            "stale_account_count": stale_count,
            "error": source_error,
        },
        "summary": {
            "configured_accounts": len(accounts),
            "enabled_accounts": len(enabled_accounts),
            "usable_now": fresh_usable_count,
            "status_counts": status_counts,
            "next_useful_capacity_at": next_useful["at"] if next_useful else None,
            "next_useful_capacity_label": next_useful["account_label"] if next_useful else None,
        },
        "forecasts": forecasts,
        "warnings": warnings,
        "events": events,
        "accounts": accounts,
        "methodology": {
            "unit": "normalized five-hour capacity point",
            "definition": "100 points equals one full five-hour account window; scheduled five-hour resets add 100 points.",
            "weekly_handling": "Weekly exhaustion blocks contribution until its reset; weekly percentages are reported separately and are not converted into five-hour points.",
            "maximum_not_prediction": True,
        },
    }


def _parse_window(value: Any, *, now: datetime, default_seconds: int) -> dict[str, Any]:
    window = value if isinstance(value, dict) else {}
    used = _percent(window.get("used_percent"))
    remaining = None if used is None else round(max(0.0, 100.0 - used), 2)
    reset_at = _parse_datetime(window.get("reset_at"))
    reset_in = None if reset_at is None else max(0, int((reset_at - now).total_seconds()))
    seconds = _integer(window.get("limit_window_seconds"), minimum=1) or default_seconds
    return {
        "used_percent": used,
        "remaining_percent": remaining,
        "reset_at": isoformat(reset_at),
        "reset_in_seconds": reset_in,
        "window_seconds": seconds,
    }


def _parse_reset_credits(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    count = _integer(payload.get("available_count", payload.get("availableCount")), minimum=0)
    raw_details = payload.get("credits")
    details: list[dict[str, Any]] = []
    if isinstance(raw_details, list):
        for raw in raw_details:
            if not isinstance(raw, dict):
                continue
            details.append(
                {
                    "reset_type": _string(raw.get("reset_type", raw.get("resetType"))),
                    "status": _string(raw.get("status")),
                    "granted_at": isoformat(_parse_datetime(raw.get("granted_at", raw.get("grantedAt")))),
                    "expires_at": isoformat(_parse_datetime(raw.get("expires_at", raw.get("expiresAt")))),
                    "title": _limited_string(raw.get("title"), 120),
                    "description": _limited_string(raw.get("description"), 300),
                }
            )
    return {
        "available_count": count,
        "details": details,
        "details_available": isinstance(raw_details, list),
        "dates_available": any(detail["granted_at"] or detail["expires_at"] for detail in details),
    }


def _forecast(
    accounts: list[dict[str, Any]],
    *,
    now: datetime,
    key: str,
    label: str,
    horizon_seconds: int,
) -> dict[str, Any]:
    horizon_end = now + timedelta(seconds=horizon_seconds)
    capacity_points = 0.0
    maximum_points = 0.0
    reset_events = 0
    contributors: set[str] = set()
    weekly_blocked = 0
    unknown_windows = 0

    for account in accounts:
        if not account["enabled"]:
            continue
        primary = account["five_hour"]
        weekly = account["weekly"]
        primary_reset = _parse_datetime(primary.get("reset_at"))
        window_seconds = int(primary.get("window_seconds") or 18_000)
        scheduled_resets = _scheduled_resets(
            first_reset=primary_reset,
            window_seconds=window_seconds,
            now=now,
            horizon_end=horizon_end,
        )
        if primary_reset is None:
            unknown_windows += 1
            theoretical_reset_count = horizon_seconds // window_seconds
        else:
            theoretical_reset_count = len(scheduled_resets)
        maximum_points += 100.0 * (1 + theoretical_reset_count)

        weekly_reset = _parse_datetime(weekly.get("reset_at"))
        weekly_limited = account["status"] == "weekly_limited"
        if weekly_limited and (weekly_reset is None or weekly_reset > horizon_end):
            weekly_blocked += 1

        if account["selectable_now"] and not account["stale"]:
            remaining = primary.get("remaining_percent")
            if isinstance(remaining, (int, float)) and remaining > 0:
                capacity_points += float(remaining)
                contributors.add(account["label"])

        if account["auth_valid"] is not True or account["stale"]:
            continue
        for reset_at in scheduled_resets:
            if weekly_limited and (weekly_reset is None or reset_at < weekly_reset):
                continue
            capacity_points += 100.0
            reset_events += 1
            contributors.add(account["label"])

    capacity_percent = 0.0 if maximum_points <= 0 else min(100.0, capacity_points / maximum_points * 100.0)
    return {
        "key": key,
        "label": label,
        "horizon_seconds": horizon_seconds,
        "capacity_points": round(capacity_points, 1),
        "account_equivalents": round(capacity_points / 100.0, 2),
        "maximum_points": round(maximum_points, 1),
        "capacity_percent": round(capacity_percent, 1),
        "usable_accounts_now": sum(1 for account in accounts if account["selectable_now"] and not account["stale"]),
        "contributing_accounts": len(contributors),
        "five_hour_resets": reset_events,
        "weekly_blocked_accounts": weekly_blocked,
        "confidence": "partial" if unknown_windows or any(account["stale"] for account in accounts if account["enabled"]) else "high",
    }


def _scheduled_resets(
    *,
    first_reset: datetime | None,
    window_seconds: int,
    now: datetime,
    horizon_end: datetime,
) -> list[datetime]:
    if first_reset is None or window_seconds <= 0:
        return []
    candidate = first_reset
    while candidate <= now:
        candidate += timedelta(seconds=window_seconds)
    resets: list[datetime] = []
    while candidate <= horizon_end:
        resets.append(candidate)
        candidate += timedelta(seconds=window_seconds)
    return resets


def _capacity_events(accounts: list[dict[str, Any]], *, now: datetime, horizon_seconds: int) -> list[dict[str, Any]]:
    horizon_end = now + timedelta(seconds=horizon_seconds)
    events: list[dict[str, Any]] = []
    for account in accounts:
        if not account["enabled"] or account["auth_valid"] is not True:
            continue
        for kind, window in (("five_hour_reset", account["five_hour"]), ("weekly_reset", account["weekly"])):
            reset_at = _parse_datetime(window.get("reset_at"))
            if reset_at is None or not now < reset_at <= horizon_end:
                continue
            events.append(
                {
                    "kind": kind,
                    "account_label": account["label"],
                    "at": isoformat(reset_at),
                    "in_seconds": int((reset_at - now).total_seconds()),
                    "capacity_points": 100 if kind == "five_hour_reset" else None,
                }
            )
        for detail in account["reset_credits"]["details"]:
            expires_at = _parse_datetime(detail.get("expires_at"))
            if expires_at is not None and now < expires_at <= horizon_end:
                events.append(
                    {
                        "kind": "reset_credit_expiry",
                        "account_label": account["label"],
                        "at": isoformat(expires_at),
                        "in_seconds": int((expires_at - now).total_seconds()),
                        "capacity_points": None,
                    }
                )
    events.sort(key=lambda event: (event["at"], event["account_label"], event["kind"]))
    return events


def _warnings(
    accounts: list[dict[str, Any]],
    *,
    source_error: str | None,
    probe_errors: dict[str, str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if source_error:
        warnings.append({"severity": "critical", "code": "source_error", "message": "Broker state refresh failed"})
    if probe_errors:
        warnings.append(
            {
                "severity": "warning",
                "code": "probe_error",
                "message": f"Freshness probe failed for {len(probe_errors)} account(s)",
            }
        )
    for account in accounts:
        status = account["status"]
        if status == "auth_invalid":
            warnings.append(
                {
                    "severity": "critical",
                    "code": "auth_invalid",
                    "account_label": account["label"],
                    "message": "Account needs login or token refresh",
                }
            )
        elif status == "unknown":
            warnings.append(
                {
                    "severity": "warning",
                    "code": "unknown",
                    "account_label": account["label"],
                    "message": account["status_reason"],
                }
            )
        if account["stale"] and account["enabled"]:
            warnings.append(
                {
                    "severity": "warning",
                    "code": "stale",
                    "account_label": account["label"],
                    "message": "Account usage state is stale",
                }
            )
        five_remaining = account["five_hour"].get("remaining_percent")
        if status == "available" and isinstance(five_remaining, (int, float)) and five_remaining <= 20:
            warnings.append(
                {
                    "severity": "warning",
                    "code": "near_zero",
                    "account_label": account["label"],
                    "message": f"Only {five_remaining:g}% of the five-hour window remains",
                }
            )
    if sum(1 for account in accounts if account["selectable_now"] and not account["stale"]) <= 1:
        warnings.append(
            {
                "severity": "critical",
                "code": "low_pool",
                "message": "One or fewer fresh accounts are selectable now",
            }
        )
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    warnings.sort(key=lambda item: (severity_rank.get(item["severity"], 9), item.get("account_label", "")))
    return warnings


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    return None


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(min(100.0, max(0.0, float(value))), 2)


def _integer(value: Any, *, minimum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= minimum else None


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _limited_string(value: Any, limit: int) -> str | None:
    text = _string(value)
    return None if text is None else text[:limit]
