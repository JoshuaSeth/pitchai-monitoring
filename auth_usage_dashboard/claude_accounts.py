"""Redacted Claude owner inventory; the dashboard never receives login files.

Run this file on the owner host once per minute. Only the official Claude CLI
reads credentials. This collector reads owner configuration and health, and
exports a small allowlisted snapshot into the dashboard's existing data mount.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {"ready", "cooldown", "sign_in_required", "unavailable"}
WINDOWS = {"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet"}
PLANS = {"max", "pro", "team", "enterprise"}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _iso(value):
    value = _number(value)
    if value is None or not 0 < value < 253402300799:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _email(value):
    if not isinstance(value, str) or len(value) > 254 or value.count("@") != 1:
        return None
    return value if all(32 < ord(c) < 127 for c in value) else None


def auth_status(cli: Path, home: Path) -> dict:
    """Read only the official CLI's identity summary, never a credential file."""
    try:
        result = subprocess.run(
            [str(cli), "auth", "status"], cwd=home, capture_output=True, text=True,
            env={"HOME": str(home), "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
            timeout=15, check=False,
        )
        value = json.loads(result.stdout)
        subscription = (value.get("loggedIn") is True and value.get("apiProvider") == "firstParty"
                        and value.get("authMethod") == "claude.ai"
                        and value.get("apiKeySource") in (None, "none"))
        return {"signed_in": subscription, "email": _email(value.get("email")),
                "plan": value.get("subscriptionType") if value.get("subscriptionType") in PLANS else None}
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        return {"signed_in": False, "email": None, "plan": None}


def collect(owner_root: Path, cli: Path, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    accounts = []
    errors = []
    for state in sorted(owner_root.glob("*/owner.json")):
        try:
            owner = json.loads(state.read_text())
            config_path = state.parent / "accounts.json"
            config = json.loads(config_path.read_text()) if config_path.exists() else {
                **owner, "accounts": [{"id": "primary", "home": "home"}]}
            if owner.get("provider") != "claude_code" or any(
                config.get(key) != owner.get(key) for key in ("tenant_id", "user_id")
            ):
                raise ValueError("profile principal mismatch")
            health_path = state.parent / "health.json"
            try:
                health = json.loads(health_path.read_text())
            except (OSError, ValueError):
                health = {}
            owner_at = _number(health.get("writtenAt")) or 0
            owner_stale = not 0 <= now - owner_at <= 60
            limits = {row["id"]: row.get("usageLimit", {}) for row in health.get("accounts", [])}
            profiles = config["accounts"]
            if not isinstance(profiles, list) or not 1 <= len(profiles) <= 8:
                raise ValueError("invalid profile inventory")
            for index, profile in enumerate(profiles):
                home = (state.parent / profile["home"]).resolve()
                if not home.is_relative_to(state.parent.resolve()):
                    raise ValueError("profile outside owner")
                auth = auth_status(cli, home)
                usage = limits.get(profile["id"], health.get("usageLimit", {}) if index == 0 else {})
                reset_at = _number(usage.get("limitedUntil"))
                observed_at = _number(usage.get("observedAt"))
                utilization = _number(usage.get("utilization"))
                used = round(utilization * 100, 1) if utilization is not None and 0 <= utilization <= 1 else None
                status = "unavailable" if owner_stale else (
                    "sign_in_required" if not auth["signed_in"] else (
                        "cooldown" if reset_at and reset_at > now else "ready"))
                fingerprint = hashlib.sha256(f"{state.parent.name}:{profile['id']}".encode()).hexdigest()[:16]
                accounts.append({
                    "id": fingerprint, **auth, "role": "Primary" if index == 0 else "Fallback",
                    "status": status, "rotation_enabled": len(profiles) > 1,
                    "owner_observed_at": owner_at, "usage_observed_at": observed_at,
                    "used_percent": used, "window": usage.get("limitType") if usage.get("limitType") in WINDOWS else None,
                    "cooldown_until": reset_at,
                })
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            errors.append("owner_inventory_unavailable")
    return {"schema_version": 1, "generated_at": now, "accounts": accounts, "errors": sorted(set(errors))}


def read_snapshot(path: Path, *, now: float | None = None) -> dict:
    """Build an explicit public schema, with no pass-through fields or errors."""
    now = time.time() if now is None else now
    unavailable = {"schema_version": 1, "generated_at": None, "stale": True,
                   "accounts": [], "error": "Claude account status is unavailable"}
    try:
        if path.stat().st_size > 262144:
            return unavailable
        raw = json.loads(path.read_text())
        generated = _number(raw.get("generated_at"))
        if raw.get("schema_version") != 1 or generated is None or not isinstance(raw.get("accounts"), list):
            return unavailable
        stale = not 0 <= now - generated <= 180
        accounts = []
        for row in raw["accounts"][:128]:
            owner_at = _number(row.get("owner_observed_at")) or 0
            status = row.get("status") if row.get("status") in STATUSES else "unavailable"
            if stale or not 0 <= now - owner_at <= 180:
                status = "unavailable"
            used = _number(row.get("used_percent"))
            observed = _number(row.get("usage_observed_at"))
            accounts.append({
                "email": _email(row.get("email")), "plan": row.get("plan") if row.get("plan") in PLANS else None,
                "role": row.get("role") if row.get("role") in {"Primary", "Fallback"} else "Account",
                "signed_in": row.get("signed_in") is True, "status": status,
                "rotation_enabled": row.get("rotation_enabled") is True,
                "used_percent": used if used is not None and 0 <= used <= 100 else None,
                "window": row.get("window") if row.get("window") in WINDOWS else None,
                "usage_observed_at": _iso(observed),
                "usage_stale": observed is None or not 0 <= now - observed <= 600,
                "cooldown_until": _iso(row.get("cooldown_until")),
            })
        return {"schema_version": 1, "generated_at": _iso(generated), "stale": stale, "accounts": accounts,
                "error": "Some Claude account status could not be read" if raw.get("errors") else None}
    except (OSError, ValueError, TypeError, AttributeError):
        return unavailable


def main():
    parser = argparse.ArgumentParser(description="Export redacted Claude account status for the usage dashboard")
    parser.add_argument("--owners", type=Path, default=Path("/var/lib/pitchai-cli-new/claude-owners"))
    parser.add_argument("--runtime", type=Path, default=Path("/opt/pitchai-claude-code-owner/current"))
    parser.add_argument("--output", type=Path, default=Path("/srv/codex-usage-dashboard/claude-accounts.json"))
    args = parser.parse_args()
    binaries = list(args.runtime.glob(".venv/lib/python*/site-packages/claude_agent_sdk/_bundled/claude"))
    if len(binaries) != 1:
        raise SystemExit("Pinned Claude binary unavailable; previous snapshot will become stale")
    snapshot = collect(args.owners, binaries[0])
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".claude-accounts-", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(snapshot, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({"accounts": len(snapshot["accounts"]), "errors": len(snapshot["errors"])}))


if __name__ == "__main__":
    main()
