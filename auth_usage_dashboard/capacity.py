from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .history import build_hourly_usage_history
from .runout import build_runout_forecast, select_capacity_basis


UTC = timezone.utc
FORECAST_HORIZONS = (
    ("hour", "Next hour", 60 * 60),
    ("six_hours", "Next 6 hours", 6 * 60 * 60),
    ("day", "Next 24 hours", 24 * 60 * 60),
)
CAPACITY_EVENT_HORIZON_SECONDS = 8 * 24 * 60 * 60


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
    rate_limit = (
        usage.get("rate_limit") if isinstance(usage.get("rate_limit"), dict) else {}
    )
    analytics = (
        state.get("analytics") if isinstance(state.get("analytics"), dict) else {}
    )
    analytics_errors = (
        analytics.get("errors") if isinstance(analytics.get("errors"), dict) else {}
    )

    label = _string(metadata.get("label")) or "Unlabeled account"
    email = _string(usage.get("email")) or label
    enabled = metadata.get("enabled", True) is not False
    availability = _string(state.get("availability")) or "unknown"
    named_windows = _named_rate_limit_windows(rate_limit)
    five_hour = _parse_window(
        named_windows["five_hour"], now=now, default_seconds=18_000
    )
    weekly = _parse_window(named_windows["weekly"], now=now, default_seconds=604_800)
    last_probe = _parse_datetime(state.get("last_probe_at"))
    stale_seconds = (
        None if last_probe is None else max(0, int((now - last_probe).total_seconds()))
    )
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
    elif (
        weekly_remaining is not None and weekly_remaining <= 0 and not weekly_reset_due
    ):
        status = "weekly_limited"
        reason = "Weekly usage window exhausted"
    elif five_remaining is not None and five_remaining <= 0 and not primary_reset_due:
        status = "five_hour_limited"
        reason = "Five-hour usage window exhausted"
    elif at_safety_floor:
        status = "five_hour_limited"
        reason = "Held at broker five-hour safety floor"
    elif availability == "rate_limited":
        if primary_reset_due or weekly_reset_due:
            status = "unknown"
            reason = "Reset is due; awaiting a fresh provider state"
        elif five_hour["reported"]:
            status = "five_hour_limited"
            reason = "Five-hour usage window limited"
        else:
            status = "unknown"
            reason = "Provider reported a limit without a five-hour window"
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
        probe_error=analytics_probe_error
        or _string(analytics_errors.get("token_usage")),
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
        credits["probe_error"] = analytics_probe_error or _string(
            analytics_errors.get("reset_credits")
        )
    else:
        credits = _parse_reset_credits(usage.get("rate_limit_reset_credits"))
        credits["source"] = "usage_summary"
        credits["updated_at"] = isoformat(last_probe)
        credits["stale"] = stale
        credits["probe_error"] = analytics_probe_error or _string(
            analytics_errors.get("reset_credits")
        )
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
        "latest_session_expires_at": isoformat(
            _parse_datetime(state.get("lease_expires_at"))
        ),
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
    usage_samples: list[dict[str, Any]] | None = None,
    history_error: str | None = None,
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
                str(
                    (raw.get("metadata") or {}).get("label")
                    or (raw.get("metadata") or {}).get("account_id")
                    or ""
                )
            ),
            analytics_probe_error=analytics_probe_errors.get(
                str(
                    (raw.get("metadata") or {}).get("label")
                    or (raw.get("metadata") or {}).get("account_id")
                    or ""
                )
            ),
        )
        for raw in raw_accounts
    ]
    accounts.sort(
        key=lambda account: (not account["enabled"], account["email"].lower())
    )

    capacity_basis = select_capacity_basis(accounts)
    forecasts = [
        _forecast(
            accounts,
            now=now,
            key=key,
            label=label,
            horizon_seconds=seconds,
            window_key=capacity_basis.get("key"),
        )
        for key, label, seconds in FORECAST_HORIZONS
    ]
    usage_history = build_hourly_usage_history(
        accounts, samples=usage_samples or [], now=now
    )
    reset_bank = _reset_bank(accounts, now=now)
    runout_forecast = build_runout_forecast(
        accounts,
        samples=usage_samples or [],
        reset_bank=reset_bank,
        now=now,
        capacity_basis=capacity_basis,
    )
    warnings = _warnings(
        accounts,
        source_error=source_error,
        history_error=history_error,
        probe_errors=probe_errors,
        analytics_probe_errors=analytics_probe_errors,
    )
    events = _capacity_events(
        accounts,
        now=now,
        horizon_seconds=CAPACITY_EVENT_HORIZON_SECONDS,
    )
    status_counts = {
        status: sum(1 for account in accounts if account["status"] == status)
        for status in (
            "available",
            "five_hour_limited",
            "weekly_limited",
            "auth_invalid",
            "disabled",
            "unknown",
        )
    }
    last_probe_values = [
        _parse_datetime(account.get("last_probe_at"))
        for account in accounts
        if account.get("last_probe_at")
    ]
    oldest_probe = min(
        (value for value in last_probe_values if value is not None), default=None
    )
    newest_probe = max(
        (value for value in last_probe_values if value is not None), default=None
    )
    enabled_accounts = [account for account in accounts if account["enabled"]]
    stale_count = sum(1 for account in enabled_accounts if account["stale"])
    analytics_stale_count = sum(
        1
        for account in enabled_accounts
        if account["token_usage"]["stale"] or account["reset_credits"]["stale"]
    )
    fresh_usable_count = sum(
        1
        for account in enabled_accounts
        if account["selectable_now"] and not account["stale"]
    )
    next_useful = next(
        (event for event in events if event["restores_selectability"]),
        next(iter(events), None),
    )
    window_aggregates = {
        "five_hour": _window_aggregate(enabled_accounts, key="five_hour"),
        "weekly": _window_aggregate(enabled_accounts, key="weekly"),
    }

    return {
        "schema_version": 4,
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
            "history_error": history_error,
            "error": source_error,
        },
        "summary": {
            "configured_accounts": len(accounts),
            "enabled_accounts": len(enabled_accounts),
            "usable_now": fresh_usable_count,
            "status_counts": status_counts,
            "window_aggregates": window_aggregates,
            "capacity_basis": capacity_basis,
            "next_useful_capacity_at": next_useful["at"] if next_useful else None,
            "next_useful_capacity_label": next_useful["account_label"]
            if next_useful
            else None,
            "capacity_event_horizon_seconds": CAPACITY_EVENT_HORIZON_SECONDS,
        },
        "forecasts": forecasts,
        "runout_forecast": runout_forecast,
        "usage_history": usage_history,
        "reset_bank": reset_bank,
        "warnings": warnings,
        "events": events,
        "accounts": accounts,
        "methodology": {
            "unit": "normalized reported-window capacity point",
            "definition": "100 points equals one full account window for the declared forecast basis. The dashboard prefers measured five-hour windows and otherwise uses measured weekly windows.",
            "weekly_handling": "Weekly exhaustion blocks selection until its provider-reported reset. When weekly is the forecast basis, its remaining percentage is used directly rather than relabeled as five-hour capacity.",
            "missing_windows": "A provider window that is not reported remains unavailable and is never converted to zero usage or zero remaining capacity.",
            "maximum_not_prediction": True,
            "token_history": "Provider daily totals are reconstructed into 168 hourly UTC points and progressively replaced by native sample deltas; the current hour is partial.",
            "runout_forecast": "Probabilities model recent percentage-point burn and automatic resets for the declared provider-window basis. Banked resets are excluded because redemption is manual and forbidden here.",
            "reset_bank": "Read-only inventory. The dashboard has no action that can consume a banked reset.",
        },
    }


def _parse_window(value: Any, *, now: datetime, default_seconds: int) -> dict[str, Any]:
    reported = isinstance(value, dict)
    window = value if reported else {}
    used = _percent(window.get("used_percent"))
    remaining = None if used is None else round(max(0.0, 100.0 - used), 2)
    reset_at = _parse_datetime(window.get("reset_at"))
    reset_in = (
        None if reset_at is None else max(0, int((reset_at - now).total_seconds()))
    )
    seconds = (
        (_integer(window.get("limit_window_seconds"), minimum=1) or default_seconds)
        if reported
        else None
    )
    return {
        "reported": reported,
        "used_percent": used,
        "remaining_percent": remaining,
        "reset_at": isoformat(reset_at),
        "reset_in_seconds": reset_in,
        "window_seconds": seconds,
    }


def _named_rate_limit_windows(
    rate_limit: dict[str, Any],
) -> dict[str, dict[str, Any] | None]:
    named: dict[str, dict[str, Any] | None] = {"five_hour": None, "weekly": None}
    unclassified: list[dict[str, Any]] = []
    for field in ("primary_window", "secondary_window"):
        window = rate_limit.get(field)
        if not isinstance(window, dict):
            continue
        seconds = _integer(window.get("limit_window_seconds"), minimum=1)
        if (
            seconds is not None
            and 4 * 60 * 60 <= seconds <= 6 * 60 * 60
            and named["five_hour"] is None
        ):
            named["five_hour"] = window
        elif (
            seconds is not None
            and seconds >= 6 * 24 * 60 * 60
            and named["weekly"] is None
        ):
            named["weekly"] = window
        else:
            unclassified.append(window)

    for key in ("five_hour", "weekly"):
        if named[key] is None and unclassified:
            named[key] = unclassified.pop(0)
    return named


def _window_aggregate(accounts: list[dict[str, Any]], *, key: str) -> dict[str, Any]:
    measured = [
        account
        for account in accounts
        if account["auth_valid"] is True
        and not account["stale"]
        and account[key].get("reported") is True
        and isinstance(account[key].get("remaining_percent"), (int, float))
    ]
    remaining_points = sum(
        float(account[key]["remaining_percent"]) for account in measured
    )
    maximum_points = float(len(measured) * 100)
    if not measured:
        measurement_status = "unavailable"
    elif len(measured) < len(accounts):
        measurement_status = "partial"
    else:
        measurement_status = "complete"
    return {
        "measurement_status": measurement_status,
        "reporting_accounts": len(measured),
        "unknown_accounts": len(accounts) - len(measured),
        "remaining_points": round(remaining_points, 1) if measured else None,
        "maximum_known_points": round(maximum_points, 1) if measured else None,
        "remaining_percent": round(remaining_points / maximum_points * 100.0, 1)
        if measured
        else None,
    }


def _parse_reset_credits(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    count = _integer(
        payload.get("available_count", payload.get("availableCount")), minimum=0
    )
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
                    "granted_at": isoformat(
                        _parse_datetime(raw.get("granted_at", raw.get("grantedAt")))
                    ),
                    "expires_at": isoformat(
                        _parse_datetime(raw.get("expires_at", raw.get("expiresAt")))
                    ),
                    "title": _limited_string(raw.get("title"), 120),
                }
            )
    return {
        "available_count": count,
        "details": details,
        "details_available": isinstance(raw_details, list),
        "dates_available": any(
            detail["granted_at"] or detail["expires_at"] for detail in details
        ),
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
    summary_payload = (
        payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    )
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
    first_day = now.date() - timedelta(days=7)
    daily: list[dict[str, Any]] = []
    raw_buckets = payload.get("daily_usage_buckets")
    if isinstance(raw_buckets, list):
        for raw in raw_buckets:
            if not isinstance(raw, dict):
                continue
            bucket_date = _parse_date(raw.get("start_date"))
            tokens = _integer(raw.get("tokens"), minimum=0)
            if (
                bucket_date is None
                or tokens is None
                or not first_day <= bucket_date <= now.date()
            ):
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
        if (
            isinstance(count, int)
            and isinstance(account_details, list)
            and count > len(account_details)
        ):
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
                        None
                        if expires_at is None
                        else int((expires_at - now).total_seconds())
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
        "stale_account_count": sum(
            1 for account in accounts if account["reset_credits"]["stale"]
        ),
    }


def _forecast(
    accounts: list[dict[str, Any]],
    *,
    now: datetime,
    key: str,
    label: str,
    horizon_seconds: int,
    window_key: str | None,
) -> dict[str, Any]:
    horizon_end = now + timedelta(seconds=horizon_seconds)
    capacity_points = 0.0
    maximum_points = 0.0
    reset_events = 0
    contributors: set[str] = set()
    weekly_blocked = 0
    unknown_windows = 0
    measured_windows = 0

    for account in accounts:
        if not account["enabled"]:
            continue
        if window_key not in {"five_hour", "weekly"}:
            unknown_windows += 1
            continue
        primary = account[window_key]
        weekly = account["weekly"]
        if primary.get("reported") is not True:
            unknown_windows += 1
            if account["status"] == "weekly_limited":
                weekly_blocked += 1
            continue
        measured_windows += 1
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
            if (
                window_key == "five_hour"
                and weekly_limited
                and (weekly_reset is None or reset_at < weekly_reset)
            ):
                continue
            capacity_points += 100.0
            reset_events += 1
            contributors.add(account["label"])

    if measured_windows == 0:
        capacity_payload: dict[str, float | None] = {
            "capacity_points": None,
            "account_equivalents": None,
            "maximum_points": None,
            "capacity_percent": None,
        }
        measurement_status = "unavailable"
    else:
        capacity_percent = min(100.0, capacity_points / maximum_points * 100.0)
        capacity_payload = {
            "capacity_points": round(capacity_points, 1),
            "account_equivalents": round(capacity_points / 100.0, 2),
            "maximum_points": round(maximum_points, 1),
            "capacity_percent": round(capacity_percent, 1),
        }
        measurement_status = "partial" if unknown_windows else "complete"
    return {
        "key": key,
        "label": label,
        "horizon_seconds": horizon_seconds,
        "basis_key": window_key,
        "basis_label": _window_label(window_key),
        **capacity_payload,
        "measurement_status": measurement_status,
        "measured_window_accounts": measured_windows,
        "unknown_window_accounts": unknown_windows,
        "usable_accounts_now": sum(
            1
            for account in accounts
            if account["selectable_now"] and not account["stale"]
        ),
        "contributing_accounts": len(contributors),
        "automatic_resets": reset_events,
        "five_hour_resets": reset_events if window_key == "five_hour" else 0,
        "weekly_blocked_accounts": weekly_blocked,
        "confidence": "unavailable"
        if not measured_windows
        else (
            "partial"
            if unknown_windows
            or any(account["stale"] for account in accounts if account["enabled"])
            else "high"
        ),
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


def _capacity_events(
    accounts: list[dict[str, Any]], *, now: datetime, horizon_seconds: int
) -> list[dict[str, Any]]:
    horizon_end = now + timedelta(seconds=horizon_seconds)
    events: list[dict[str, Any]] = []
    for account in accounts:
        if not account["enabled"] or account["auth_valid"] is not True:
            continue
        for kind, window in (
            ("five_hour_reset", account["five_hour"]),
            ("weekly_reset", account["weekly"]),
        ):
            if window.get("reported") is not True:
                continue
            reset_at = _parse_datetime(window.get("reset_at"))
            if reset_at is None or not now < reset_at <= horizon_end:
                continue
            events.append(
                {
                    "kind": kind,
                    "account_label": account["label"],
                    "at": isoformat(reset_at),
                    "in_seconds": int((reset_at - now).total_seconds()),
                    "capacity_points": 100,
                    "restores_selectability": (
                        kind == "five_hour_reset"
                        and account["status"] == "five_hour_limited"
                    )
                    or (
                        kind == "weekly_reset" and account["status"] == "weekly_limited"
                    ),
                }
            )
    events.sort(key=lambda event: (event["at"], event["account_label"], event["kind"]))
    return events


def _window_label(key: str | None) -> str | None:
    if key == "five_hour":
        return "Five-hour"
    if key == "weekly":
        return "Weekly"
    return None


def _warnings(
    accounts: list[dict[str, Any]],
    *,
    source_error: str | None,
    history_error: str | None,
    probe_errors: dict[str, str],
    analytics_probe_errors: dict[str, str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if source_error:
        warnings.append(
            {
                "severity": "critical",
                "code": "source_error",
                "message": "Broker state refresh failed",
            }
        )
    if history_error:
        warnings.append(
            {
                "severity": "warning",
                "code": "history_error",
                "message": "Usage sample history could not be persisted",
            }
        )
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
    five_hour_unreported = sum(
        1
        for account in accounts
        if account["enabled"]
        and account["auth_valid"] is True
        and not account["stale"]
        and account["five_hour"].get("reported") is not True
    )
    if five_hour_unreported:
        warnings.append(
            {
                "severity": "info",
                "code": "five_hour_unreported",
                "message": f"Provider did not report a five-hour window for {five_hour_unreported} auth-valid account(s)",
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
        if (
            status == "available"
            and isinstance(five_remaining, (int, float))
            and five_remaining <= 20
        ):
            warnings.append(
                {
                    "severity": "warning",
                    "code": "near_zero",
                    "account_label": account["label"],
                    "message": f"Only {five_remaining:g}% of the five-hour window remains",
                }
            )
    if (
        sum(
            1
            for account in accounts
            if account["selectable_now"] and not account["stale"]
        )
        <= 1
    ):
        warnings.append(
            {
                "severity": "critical",
                "code": "low_pool",
                "message": "One or fewer fresh accounts are selectable now",
            }
        )
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    warnings.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 9),
            item.get("account_label", ""),
        )
    )
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
            return datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")
            ).astimezone(UTC)
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
