from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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
    analytics_stale_after_seconds: int = 1800,
    probe_error: str | None = None,
    analytics_probe_error: str | None = None,
) -> dict[str, Any]:
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    state = raw.get("state") if isinstance(raw.get("state"), dict) else {}
    usage = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    rate_limit = usage.get("rate_limit") if isinstance(usage.get("rate_limit"), dict) else {}
    analytics = state.get("analytics") if isinstance(state.get("analytics"), dict) else {}
    analytics_errors = analytics.get("errors") if isinstance(analytics.get("errors"), dict) else {}

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

    token_usage = _parse_token_usage(
        analytics.get("token_usage"),
        updated_at=analytics.get("token_usage_updated_at"),
        now=now,
        stale_after_seconds=analytics_stale_after_seconds,
        probe_error=analytics_probe_error or _string(analytics_errors.get("token_usage")),
    )
    analytics_reset_credits = analytics.get("reset_credits")
    if isinstance(analytics_reset_credits, dict):
        credits = _parse_reset_credits(analytics_reset_credits)
        credits["source"] = "provider_reset_inventory"
        reset_updated_at = _parse_datetime(analytics.get("reset_credits_updated_at"))
        credits["updated_at"] = isoformat(reset_updated_at)
        credits["stale"] = (
            reset_updated_at is None
            or (now - reset_updated_at).total_seconds() > analytics_stale_after_seconds
        )
        credits["probe_error"] = analytics_probe_error or _string(analytics_errors.get("reset_credits"))
    else:
        credits = _parse_reset_credits(usage.get("rate_limit_reset_credits"))
        credits["source"] = "usage_summary"
        credits["updated_at"] = isoformat(last_probe)
        credits["stale"] = stale
        credits["probe_error"] = analytics_probe_error or _string(analytics_errors.get("reset_credits"))
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
        "token_usage": token_usage,
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
    analytics_stale_after_seconds: int = 1800,
    probe_errors: dict[str, str] | None = None,
    analytics_probe_errors: dict[str, str] | None = None,
    source_error: str | None = None,
    last_safe_probe_at: datetime | None = None,
    last_analytics_probe_at: datetime | None = None,
    probe_interval_seconds: int = 300,
    analytics_probe_interval_seconds: int = 900,
) -> dict[str, Any]:
    probe_errors = probe_errors or {}
    analytics_probe_errors = analytics_probe_errors or {}
    accounts = [
        parse_account(
            raw,
            now=now,
            stale_after_seconds=stale_after_seconds,
            analytics_stale_after_seconds=analytics_stale_after_seconds,
            min_five_hour_remaining_percent=min_five_hour_remaining_percent,
            probe_error=probe_errors.get(
                str((raw.get("metadata") or {}).get("label") or (raw.get("metadata") or {}).get("account_id") or "")
            ),
            analytics_probe_error=analytics_probe_errors.get(
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
    usage_history = _usage_history(accounts, now=now)
    reset_bank = _reset_bank(accounts, now=now)
    warnings = _warnings(
        accounts,
        source_error=source_error,
        probe_errors=probe_errors,
        analytics_probe_errors=analytics_probe_errors,
    )
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
    analytics_stale_count = sum(
        1
        for account in enabled_accounts
        if account["token_usage"]["stale"] or account["reset_credits"]["stale"]
    )
    fresh_usable_count = sum(
        1 for account in enabled_accounts if account["selectable_now"] and not account["stale"]
    )
    next_useful = next((event for event in events if event["kind"] in {"five_hour_reset", "weekly_reset"}), None)

    return {
        "schema_version": 2,
        "generated_at": isoformat(now),
        "source": {
            "name": "authoritative Codex authentication broker",
            "mode": "read-only state files plus no-generation usage and analytics probes",
            "probe_interval_seconds": probe_interval_seconds,
            "analytics_probe_interval_seconds": analytics_probe_interval_seconds,
            "last_safe_probe_at": isoformat(last_safe_probe_at),
            "last_analytics_probe_at": isoformat(last_analytics_probe_at),
            "oldest_account_probe_at": isoformat(oldest_probe),
            "newest_account_probe_at": isoformat(newest_probe),
            "stale": bool(source_error or stale_count or analytics_stale_count),
            "stale_account_count": stale_count,
            "analytics_stale_account_count": analytics_stale_count,
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
        "usage_history": usage_history,
        "reset_bank": reset_bank,
        "warnings": warnings,
        "events": events,
        "accounts": accounts,
        "methodology": {
            "unit": "normalized five-hour capacity point",
            "definition": "100 points equals one full five-hour account window; scheduled five-hour resets add 100 points.",
            "weekly_handling": "Weekly exhaustion blocks contribution until its reset; weekly percentages are reported separately and are not converted into five-hour points.",
            "maximum_not_prediction": True,
            "token_history": "Provider-reported token activity grouped by UTC day; the current day is partial.",
            "reset_bank": "Read-only inventory. The dashboard has no action that can consume a banked reset.",
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
                }
            )
    return {
        "available_count": count,
        "details": details,
        "details_available": isinstance(raw_details, list),
        "dates_available": any(detail["granted_at"] or detail["expires_at"] for detail in details),
    }


def _parse_token_usage(
    value: Any,
    *,
    updated_at: Any,
    now: datetime,
    stale_after_seconds: int,
    probe_error: str | None,
) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    summary_payload = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    summary = {
        key: _integer(summary_payload.get(key), minimum=0)
        for key in (
            "lifetime_tokens",
            "peak_daily_tokens",
            "longest_running_turn_sec",
            "current_streak_days",
            "longest_streak_days",
        )
    }
    first_day = now.date() - timedelta(days=6)
    daily: list[dict[str, Any]] = []
    raw_buckets = payload.get("daily_usage_buckets")
    if isinstance(raw_buckets, list):
        for raw in raw_buckets:
            if not isinstance(raw, dict):
                continue
            bucket_date = _parse_date(raw.get("start_date"))
            tokens = _integer(raw.get("tokens"), minimum=0)
            if bucket_date is None or tokens is None or not first_day <= bucket_date <= now.date():
                continue
            daily.append({"date": bucket_date.isoformat(), "tokens": tokens})
    daily.sort(key=lambda item: item["date"])
    parsed_updated_at = _parse_datetime(updated_at)
    stale = (
        parsed_updated_at is None
        or (now - parsed_updated_at).total_seconds() > stale_after_seconds
    )
    return {
        "available": isinstance(value, dict),
        "granularity": "day",
        "daily": daily,
        "summary": summary,
        "updated_at": isoformat(parsed_updated_at),
        "stale": stale,
        "probe_error": probe_error,
    }


def _usage_history(accounts: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    dates = [(now.date() - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]
    reporting = [account for account in accounts if account["token_usage"]["available"]]
    series: list[dict[str, Any]] = []
    combined = {day: 0 for day in dates}
    for account in reporting:
        values = {point["date"]: point["tokens"] for point in account["token_usage"]["daily"]}
        points = []
        for day in dates:
            tokens = int(values.get(day, 0))
            combined[day] += tokens
            points.append({"date": day, "at": f"{day}T00:00:00Z", "tokens": tokens})
        series.append(
            {
                "label": account["label"],
                "points": points,
                "updated_at": account["token_usage"]["updated_at"],
                "stale": account["token_usage"]["stale"],
            }
        )
    series.sort(key=lambda item: item["label"].lower())
    combined_points = [
        {
            "date": day,
            "at": f"{day}T00:00:00Z",
            "tokens": combined[day],
            "accounts_reporting": len(reporting),
        }
        for day in dates
    ]
    totals = [point["tokens"] for point in combined_points]
    updated_values = [
        _parse_datetime(account["token_usage"].get("updated_at"))
        for account in reporting
    ]
    valid_updates = [value for value in updated_values if value is not None]
    total_tokens = sum(totals)
    return {
        "granularity": "day",
        "provider_granularity": "daily",
        "timezone": "UTC",
        "period_start": f"{dates[0]}T00:00:00Z",
        "period_end": isoformat(now),
        "current_day_partial": True,
        "accounts_reporting": len(reporting),
        "configured_accounts": len(accounts),
        "stale_account_count": sum(1 for account in reporting if account["token_usage"]["stale"]),
        "updated_at": isoformat(min(valid_updates, default=None)),
        "combined": combined_points,
        "series": series,
        "summary": {
            "seven_day_tokens": total_tokens,
            "average_daily_tokens": round(total_tokens / len(dates)),
            "peak_daily_tokens": max(totals, default=0),
            "today_tokens": totals[-1] if totals else 0,
        },
    }


def _reset_bank(accounts: list[dict[str, Any]], *, now: datetime) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    known_counts: list[int] = []
    count_only_accounts = 0
    for account in accounts:
        reset_credits = account["reset_credits"]
        count = reset_credits.get("available_count")
        account_details = reset_credits.get("details")
        if isinstance(count, int):
            known_counts.append(count)
        if isinstance(count, int) and isinstance(account_details, list) and count > len(account_details):
            count_only_accounts += 1
        if not isinstance(account_details, list):
            continue
        for detail in account_details:
            expires_at = _parse_datetime(detail.get("expires_at"))
            details.append(
                {
                    "account_label": account["label"],
                    "reset_type": detail.get("reset_type"),
                    "status": detail.get("status"),
                    "title": detail.get("title"),
                    "granted_at": detail.get("granted_at"),
                    "expires_at": detail.get("expires_at"),
                    "expires_in_seconds": (
                        None if expires_at is None else int((expires_at - now).total_seconds())
                    ),
                }
            )
    details.sort(
        key=lambda item: (
            item["expires_at"] is None,
            item["expires_at"] or "",
            item["account_label"].lower(),
        )
    )
    future_expiries = []
    for detail in details:
        parsed_expiry = _parse_datetime(detail.get("expires_at"))
        if parsed_expiry is not None and parsed_expiry > now:
            future_expiries.append(parsed_expiry)
    return {
        "total_available": sum(known_counts),
        "accounts_with_known_count": len(known_counts),
        "accounts_with_unknown_count": len(accounts) - len(known_counts),
        "count_only_accounts": count_only_accounts,
        "detail_count": len(details),
        "details": details,
        "earliest_expiry_at": isoformat(min(future_expiries, default=None)),
        "stale_account_count": sum(1 for account in accounts if account["reset_credits"]["stale"]),
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
    analytics_probe_errors: dict[str, str],
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
    if analytics_probe_errors:
        warnings.append(
            {
                "severity": "warning",
                "code": "analytics_probe_error",
                "message": f"Token history or reset-bank refresh failed for {len(analytics_probe_errors)} account(s)",
            }
        )
    analytics_stale_count = sum(
        1
        for account in accounts
        if account["enabled"]
        and (account["token_usage"]["stale"] or account["reset_credits"]["stale"])
    )
    if analytics_stale_count:
        warnings.append(
            {
                "severity": "warning",
                "code": "analytics_stale",
                "message": f"Usage history or reset-bank data is stale for {analytics_stale_count} account(s)",
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


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
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
