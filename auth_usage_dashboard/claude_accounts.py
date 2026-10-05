# Copyright (c) 2026 PitchAI. All rights reserved.
"""Redacted Claude owner inventory for the usage dashboard.

Only the official Claude CLI reads credentials; this collector asks it for each
profile's plan-limit readout and allowlisted identity summary, then writes a
redacted snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .claude_probe import QuotaProbe, QuotaSettings, run_cli
from .claude_quota import apply_quota, number_value, object_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .timeseries_types import JsonObject, JsonValue

SCHEMA_VERSION = 1
CLAUDE_ACCOUNTS_FILE = Path("/dashboard-data/claude-accounts.json")
COLLECTOR_OUTPUT_FILE = Path("/srv/codex-usage-dashboard/claude-accounts.json")
DEFAULT_OWNERS_ROOT = Path("/var/lib/pitchai-cli-new/claude-owners")
DEFAULT_RUNTIME_ROOT = Path("/opt/pitchai-claude-code-owner/current")
BUNDLED_BINARY_GLOB = ".venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude"
MINIMUM_UTILIZATION, MAXIMUM_UTILIZATION, FRESH_SECONDS = 0.0, 1.0, 60.0
MAX_EMAIL_LENGTH, MAX_SNAPSHOT_BYTES = 254, 262_144
MINIMUM_PROFILES, MAXIMUM_PROFILES, FIRST_VISIBLE_ORDINAL, LAST_VISIBLE_ORDINAL = 1, 8, 33, 126
FINGERPRINT_LENGTH, SNAPSHOT_DIRECTORY_MODE, SNAPSHOT_SUFFIX, AUTH_TIMEOUT_SECONDS = 16, 0o700, ".partial", 60.0
WINDOWS = frozenset({"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"})
PLANS = frozenset({"max", "pro", "team", "enterprise"})
OWNER_UNAVAILABLE_ERROR = "owner_inventory_unavailable"
MISSING_BINARY_MESSAGE = "Pinned Claude binary unavailable; previous snapshot will become stale\n"
FALLBACK_PROFILES: list[JsonValue] = [{"id": "primary", "home": "home"}]


def member_value(value: JsonValue, allowed: frozenset[str]) -> str | None:
    """Return the value when it is one of the allowed members."""
    return value if isinstance(value, str) and value in allowed else None


def email_value(value: JsonValue) -> str | None:
    """Return one printable single-at-sign address, or nothing."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_EMAIL_LENGTH or value.count("@") != 1:
        return None
    visible = (FIRST_VISIBLE_ORDINAL <= ord(character) <= LAST_VISIBLE_ORDINAL for character in value)
    return value if all(visible) else None


def _decode_object(text: str | None) -> JsonObject:
    value: JsonValue | None = None
    with suppress(ValueError):
        value = cast("JsonValue", json.loads(text or ""))
    return object_value(value)


def load_json_object(path: Path) -> JsonObject | None:
    """Return one size-capped JSON object, or nothing when unreadable."""
    text: str | None = None
    with suppress(OSError):
        if path.stat().st_size <= MAX_SNAPSHOT_BYTES:
            text = path.read_text(encoding="utf-8")
    return None if text is None else _decode_object(text)


def auth_status(cli: Path, home: Path) -> JsonObject:
    """Return the official CLI's allowlisted identity summary for one owner home."""
    environment = {"HOME": str(home), "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
    document = _decode_object(run_cli((str(cli), "auth", "status"), environment, home, AUTH_TIMEOUT_SECONDS).stdout)
    key_source = document.get("apiKeySource")
    signed_in = (
        document.get("loggedIn") is True
        and document.get("apiProvider") == "firstParty"
        and document.get("authMethod") == "claude.ai"
        and key_source in {None, "none"}
    )
    email = email_value(document.get("email"))
    plan = member_value(document.get("subscriptionType"), PLANS)
    return {"signed_in": signed_in, "email": email, "plan": plan}


def _profile_entries(root: Path, configuration: JsonObject) -> list[tuple[str, Path]] | None:
    profiles = configuration.get("accounts")
    if not isinstance(profiles, list) or not MINIMUM_PROFILES <= len(profiles) <= MAXIMUM_PROFILES:
        return None
    owner_root = root.resolve()
    entries: list[tuple[str, Path]] = []
    for profile in profiles:
        identifier = profile.get("id") if isinstance(profile, dict) else None
        home_name = profile.get("home") if isinstance(profile, dict) else None
        home = (root / home_name).resolve() if isinstance(home_name, str) else None
        if not isinstance(identifier, str) or home is None or not home.is_relative_to(owner_root):
            return None
        entries.append((identifier, home))
    return entries


def _usage_limit(health: JsonObject, identifier: str, index: int) -> JsonObject:
    rows = health.get("accounts")
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("id") == identifier:
            return object_value(row.get("usageLimit"))
    return object_value(health.get("usageLimit")) if index == 0 else {}


def _row_status(auth: JsonObject, reset_at: float | None, *, stale: bool, now: float) -> str:
    if stale:
        return "unavailable"
    if auth.get("signed_in") is not True:
        return "sign_in_required"
    return "cooldown" if reset_at is not None and reset_at > now else "ready"


@dataclass(frozen=True)
class _Context:
    state_name: str
    observed_at: float
    rotation: bool
    stale: bool
    now: float
    cli: Path
    probe: QuotaProbe | None


def _row_id(state_name: str, identifier: str) -> str:
    return hashlib.sha256(f"{state_name}:{identifier}".encode()).hexdigest()[:FINGERPRINT_LENGTH]


def _account_row(context: _Context, identifier: str, auth: JsonObject, usage: JsonObject, index: int) -> JsonObject:
    reset_at = number_value(usage.get("limitedUntil"))
    utilization = number_value(usage.get("utilization"))
    used_percent = None
    if utilization is not None and MINIMUM_UTILIZATION <= utilization <= MAXIMUM_UTILIZATION:
        used_percent = round(utilization * 100.0, 1)
    return {
        "id": _row_id(context.state_name, identifier),
        "signed_in": auth.get("signed_in") is True,
        "email": email_value(auth.get("email")),
        "plan": member_value(auth.get("plan"), PLANS),
        "role": "Primary" if index == 0 else "Fallback",
        "status": _row_status(auth, reset_at, stale=context.stale, now=context.now),
        "rotation_enabled": context.rotation,
        "owner_observed_at": context.observed_at,
        "usage_observed_at": number_value(usage.get("observedAt")),
        "used_percent": used_percent,
        "window": member_value(usage.get("limitType"), WINDOWS),
        "cooldown_until": reset_at,
    }


def _profile_row(context: _Context, health: JsonObject, index: int, profile: tuple[str, Path]) -> JsonValue:
    identifier, home = profile
    quota: JsonObject | None = None
    if context.probe is not None:  # Before `auth status`: an expired token's status call leaves a refresh lock.
        quota = context.probe.reading(_row_id(context.state_name, identifier), home, now=context.now)
    usage = _usage_limit(health, identifier, index)
    row = _account_row(context, identifier, auth_status(context.cli, home), usage, index)
    return row if quota is None else apply_quota(row, quota, now=context.now)


def _owner_rows(state: Path, cli: Path, probe: QuotaProbe | None, *, now: float) -> list[JsonValue] | None:
    owner = load_json_object(state)
    if owner is None or owner.get("provider") != "claude_code":
        return None
    configuration = load_json_object(state.parent / "accounts.json") or {**owner, "accounts": FALLBACK_PROFILES}
    mismatch = any(configuration.get(key) != owner.get(key) for key in ("tenant_id", "user_id"))
    entries = None if mismatch else _profile_entries(state.parent, configuration)
    if entries is None:
        return None
    health = load_json_object(state.parent / "health.json") or {}
    observed = number_value(health.get("writtenAt")) or 0.0
    stale = not 0 <= now - observed <= FRESH_SECONDS
    context = _Context(state.parent.name, observed, len(entries) > 1, stale, now, cli, probe)
    return [_profile_row(context, health, index, entry) for index, entry in enumerate(entries)]


def collect(owner_root: Path, cli: Path, *, now: float | None = None, quota: QuotaSettings | None = None) -> JsonObject:
    """Return the redacted Claude inventory from every owner directory, with plan limits when configured."""
    current = time.time() if now is None else now
    probe = None if quota is None else QuotaProbe(cli, quota)
    rows: list[JsonValue] = []
    failures = 0
    for state in sorted(owner_root.glob("*/owner.json")):
        owner_rows = _owner_rows(state, cli, probe, now=current)
        if owner_rows is None:
            failures += 1
            continue
        rows.extend(owner_rows)
    errors: list[JsonValue] = [OWNER_UNAVAILABLE_ERROR] if failures else []
    return {"schema_version": SCHEMA_VERSION, "generated_at": current, "accounts": rows, "errors": errors}


def previous_rows(path: Path) -> dict[str, JsonValue]:
    """Return the rows of this exporter's previous snapshot by stable id, to carry quota readings forward."""
    document = load_json_object(path) or {}
    rows = document.get("accounts") if document.get("schema_version") == SCHEMA_VERSION else None
    previous: dict[str, JsonValue] = {}
    for row in rows if isinstance(rows, list) else []:
        identifier = object_value(row).get("id")
        if isinstance(identifier, str):
            previous[identifier] = row
    return previous


def main(argv: Sequence[str] | None = None) -> int:
    """Return zero after writing one redacted Claude inventory snapshot."""
    parser = argparse.ArgumentParser(description="Export redacted Claude account status for the usage dashboard")
    parser.add_argument("--owners", type=Path, default=DEFAULT_OWNERS_ROOT)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--output", type=Path, default=COLLECTOR_OUTPUT_FILE)
    defaults = QuotaSettings({})
    parser.add_argument("--quota-interval", type=float, default=defaults.interval)
    parser.add_argument("--probe-guard", type=Path, default=defaults.guard)
    parser.add_argument("--probe-timeout", type=float, default=defaults.timeout)
    parser.add_argument("--probe-budget", type=float, default=defaults.budget)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    binaries = sorted(cast("Path", arguments.runtime).glob(BUNDLED_BINARY_GLOB))
    if len(binaries) != 1:
        sys.stderr.write(MISSING_BINARY_MESSAGE)
        return 1
    output = cast("Path", arguments.output)
    guard, interval = cast("Path", arguments.probe_guard), cast("float", arguments.quota_interval)
    timeout, budget = cast("float", arguments.probe_timeout), cast("float", arguments.probe_budget)
    quota = QuotaSettings(previous_rows(output), guard=guard, interval=interval, timeout=timeout, budget=budget)
    document = collect(cast("Path", arguments.owners), binaries[0], quota=quota)
    output.parent.mkdir(parents=True, exist_ok=True, mode=SNAPSHOT_DIRECTORY_MODE)
    temporary = output.with_name(output.name + SNAPSHOT_SUFFIX)
    temporary.write_text(json.dumps(document, allow_nan=False), encoding="utf-8")
    temporary.replace(output)
    accounts = len(cast("list[JsonValue]", document.get("accounts")))
    errors = len(cast("list[JsonValue]", document.get("errors")))
    sys.stdout.write(json.dumps({"accounts": accounts, "errors": errors}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
