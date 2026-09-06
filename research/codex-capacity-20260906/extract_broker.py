"""Read existing broker history; emit only allowlisted, pseudonymous telemetry.

Run on the broker host using its system Python. No provider requests are made.
Account aliases use the sorted durable-store references at the cutoff. The
guardian uses a different reference namespace, joined by exact broker labels
inside this process only. Labels, original references and errors never leave it.
"""

import argparse
import datetime
import json
import pathlib
import sqlite3
import sys


def emit(kind, **fields):
    """Write one deliberately bounded telemetry record."""
    print(json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":")))


def database(path):
    """Hold a consistent read transaction, without copying or modifying a DB."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def window(value):
    """Preserve reported units and timestamps, without assuming window position."""
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in (
        "used_percent", "limit_window_seconds", "reset_at", "reset_after_seconds",
    )}


def main():
    """Export durable samples, guardian observations and known redemptions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True, help="Exclusive ISO UTC cutoff")
    args = parser.parse_args()
    quota = database("/srv/codex-usage-dashboard/usage-history.sqlite3")
    guardian = database("/var/lib/pitchai-auth-reset-guardian/audit.sqlite3")
    identities = list(quota.execute(
        "SELECT DISTINCT account_ref, account_label FROM account_usage_samples "
        "WHERE sampled_at < ? ORDER BY account_ref", (args.cutoff,),
    ))
    refs = sorted({row["account_ref"] for row in identities})
    aliases = {ref: f"A{index:02d}" for index, ref in enumerate(refs, start=1)}
    labels = {row["account_label"]: aliases[row["account_ref"]] for row in identities}
    if len(labels) != len(refs):
        raise ValueError("Account labels are not a bijection; review identity history")
    emit("manifest", cutoff=args.cutoff, accounts=len(refs), schema=1,
         extracted_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         identity_rule="durable reference order; exact guardian-label join",
         cutoff_rule="row capture time strictly before cutoff")
    samples = quota.execute(
        "SELECT * FROM account_usage_samples WHERE sampled_at < ? ORDER BY sample_id",
        (args.cutoff,),
    )
    for row in samples:
        fields = {key: row[key] for key in (
            "sample_id", "batch_id", "sampled_at", "enabled", "auth_state",
            "account_status", "availability", "five_used_percent",
            "five_remaining_percent", "five_reset_at", "five_window_seconds",
            "weekly_used_percent", "weekly_remaining_percent", "weekly_reset_at",
            "weekly_window_seconds", "redeemable_count", "provider_observed_at",
            "provider_age_seconds", "provider_stale", "reset_inventory_observed_at",
            "reset_inventory_stale", "token_usage_observed_at", "token_usage_stale",
            "values_source", "token_date", "tokens_today", "source", "collector_version",
        )}
        fields["carried_fields"] = json.loads(row["carried_fields_json"])
        for key in ("probe_error", "reset_inventory_error", "token_usage_error"):
            fields[f"has_{key}"] = bool(row[key])
        emit("quota_sample", account=aliases[row["account_ref"]], **fields)
    credits = {}

    def credit_alias(account, reference):
        key = (account, reference)
        if key not in credits:
            credits[key] = f"C{len(credits) + 1:03d}"
        return credits[key]

    for row in guardian.execute(
        "SELECT * FROM snapshots WHERE captured_at < ? ORDER BY snapshot_id", (args.cutoff,),
    ):
        account = labels[row["account_label"]]
        state = json.loads(row["state_json"])
        usage = state.get("usage_state") or {}
        broker = state.get("broker_state") or {}
        observed_credits = []
        for credit in state.get("credits", []):
            observed_credits.append({
                "credit": credit_alias(account, credit["credit_ref"]),
                **{key: credit.get(key) for key in (
                    "expires_at", "granted_at", "redeemable", "reset_type", "status",
                    "supported_by_plan",
                )},
            })
        emit("guardian_snapshot", account=account, snapshot_id=row["snapshot_id"],
             captured_at=row["captured_at"], phase=row["phase"],
             available_count=state.get("available_count"), credits=observed_credits,
             primary=window(usage.get("primary_window")),
             secondary=window(usage.get("secondary_window")),
             allowed=usage.get("allowed"), limit_reached=usage.get("limit_reached"),
             applicable_reset_count=usage.get("applicable_reset_count"),
             available_reset_count=usage.get("available_reset_count"),
             provider_observed_at=broker.get("last_probe_at"))
    for row in guardian.execute(
        "SELECT * FROM redemption_attempts WHERE started_at < ? ORDER BY started_at",
        (args.cutoff,),
    ):
        account = labels[row["account_label"]]
        emit("redemption", account=account,
             credit=credit_alias(account, row["credit_ref"]),
             **{key: row[key] for key in (
                 "started_at", "updated_at", "expires_at", "status", "outcome",
                 "windows_reset", "verification", "error_code",
             )})
    for row in guardian.execute(
        "SELECT event_type, severity, COUNT(*) AS n, MIN(occurred_at) AS first_at, "
        "MAX(occurred_at) AS last_at FROM events WHERE occurred_at < ? GROUP BY 1,2",
        (args.cutoff,),
    ):
        emit("guardian_event_summary", **dict(row))
    for directory in sorted(pathlib.Path("/srv/auth-token-server/data/accounts").iterdir()):
        if not directory.is_dir():
            continue
        metadata = json.loads((directory / "metadata.json").read_text())
        state = json.loads((directory / "state.json").read_text())
        account = labels[metadata["label"]]
        usage = state.get("usage") or {}
        emit("current_plan_observation", account=account,
             provider_observed_at=state.get("last_probe_at"),
             plan_type=usage.get("plan_type"), metadata_created_at=metadata.get("created_at"),
             observation_scope="current overwritten broker state; not historical plan proof")
    quota.close()
    guardian.close()


if __name__ == "__main__":
    sys.exit(main())
