# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read existing broker history; emit only allowlisted, pseudonymous telemetry.

Run on the broker host using Python 3.12. No provider requests are made.
Account aliases use the sorted durable-store references at the cutoff. The
guardian uses a different reference namespace, joined by exact broker labels
inside this process only. Labels, original references and errors never leave it.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

type Json = str | int | float | bool | Sequence[Json] | Mapping[str, Json] | None
type Record = dict[str, Json]
type Credits = dict[tuple[str, str], str]

SAMPLE_FIELDS = (
    "sample_id", "batch_id", "sampled_at", "enabled", "auth_state",
    "account_status", "availability", "five_used_percent",
    "five_remaining_percent", "five_reset_at", "five_window_seconds",
    "weekly_used_percent", "weekly_remaining_percent", "weekly_reset_at",
    "weekly_window_seconds", "redeemable_count", "provider_observed_at",
    "provider_age_seconds", "provider_stale", "reset_inventory_observed_at",
    "reset_inventory_stale", "token_usage_observed_at", "token_usage_stale",
    "values_source", "token_date", "tokens_today", "source", "collector_version",
)
CREDIT_FIELDS = ("expires_at", "granted_at", "redeemable", "reset_type", "status", "supported_by_plan")
REDEMPTION_FIELDS = (
    "started_at", "updated_at", "expires_at", "status", "outcome", "windows_reset", "verification", "error_code",
)


def emit(kind: str, **fields: Json) -> None:
    """Write one deliberately bounded telemetry record."""
    sys.stdout.write(json.dumps({"kind": kind, **fields}, sort_keys=True, separators=(",", ":")) + "\n")


def database(path: str) -> sqlite3.Connection:
    """Hold a consistent read transaction without copying or modifying a DB.

    Returns:
        A read-only connection whose lifetime belongs to the caller.
    """
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def window(value: Json) -> Record | None:
    """Preserve reported units and timestamps without assuming window position.

    Returns:
        The four allowlisted window fields, or None for absent window evidence.
    """
    if not isinstance(value, dict):
        return None
    return {key: value.get(key) for key in (
        "used_percent", "limit_window_seconds", "reset_at", "reset_after_seconds",
    )}


def account_aliases(quota: sqlite3.Connection, cutoff: str) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve the two private identity namespaces inside the extraction process.

    Returns:
        Durable-reference aliases and the corresponding exact-label aliases.

    Raises:
        ValueError: Labels and references cannot be joined bijectively.
    """
    identities = cast("list[sqlite3.Row]", list(quota.execute(
        "SELECT DISTINCT account_ref, account_label FROM account_usage_samples "
        "WHERE sampled_at < ? ORDER BY account_ref", (cutoff,),
    )))
    references = {cast("str", row["account_ref"]) for row in identities}
    refs = sorted(references)
    indexed_refs = enumerate(refs, start=1)
    aliases = {ref: f"A{index:02d}" for index, ref in indexed_refs}
    labels: dict[str, str] = {}
    for row in identities:
        labels[cast("str", row["account_label"])] = aliases[cast("str", row["account_ref"])]
    if len(labels) != len(refs):
        message = "Account labels are not a bijection; review identity history"
        raise ValueError(message)
    return aliases, labels


def samples(quota: sqlite3.Connection, cutoff: str, aliases: dict[str, str]) -> None:
    """Project historical usage rows without exporting private error strings."""
    rows = cast("Iterator[sqlite3.Row]", quota.execute(
        "SELECT * FROM account_usage_samples WHERE sampled_at < ? ORDER BY sample_id", (cutoff,),
    ))
    for row in rows:
        fields = {key: cast("Json", row[key]) for key in SAMPLE_FIELDS}
        fields["carried_fields"] = cast("Json", json.loads(cast("str", row["carried_fields_json"])))
        for key in ("probe_error", "reset_inventory_error", "token_usage_error"):
            fields[f"has_{key}"] = bool(cast("Json", row[key]))
        emit("quota_sample", account=aliases[cast("str", row["account_ref"])], **fields)


def credit_alias(credit_ids: Credits, account: str, reference: str) -> str:
    """Assign one stable local alias to a credit in its account namespace.

    Returns:
        The existing or next sequential credit alias.
    """
    key = (account, reference)
    if key not in credit_ids:
        credit_ids[key] = f"C{len(credit_ids) + 1:03d}"
    return credit_ids[key]


def snapshots(guardian: sqlite3.Connection, cutoff: str, labels: dict[str, str], credit_ids: Credits) -> None:
    """Export guardian quota and inventory snapshots in capture order."""
    rows = cast("Iterator[sqlite3.Row]", guardian.execute(
        "SELECT * FROM snapshots WHERE captured_at < ? ORDER BY snapshot_id", (cutoff,),
    ))
    for row in rows:
        account = labels[cast("str", row["account_label"])]
        state = cast("Record", json.loads(cast("str", row["state_json"])))
        usage = cast("Record", state.get("usage_state") or {})
        broker = cast("Record", state.get("broker_state") or {})
        observed_credits: list[Record] = []
        for credit in cast("list[Record]", state.get("credits", [])):
            fields = {key: credit.get(key) for key in CREDIT_FIELDS}
            fields["credit"] = credit_alias(credit_ids, account, cast("str", credit["credit_ref"]))
            observed_credits.append(fields)
        emit("guardian_snapshot", account=account, snapshot_id=cast("Json", row["snapshot_id"]),
             captured_at=cast("Json", row["captured_at"]), phase=cast("Json", row["phase"]),
             available_count=state.get("available_count"), credits=observed_credits,
             primary=window(usage.get("primary_window")), secondary=window(usage.get("secondary_window")),
             allowed=usage.get("allowed"), limit_reached=usage.get("limit_reached"),
             applicable_reset_count=usage.get("applicable_reset_count"),
             available_reset_count=usage.get("available_reset_count"),
             provider_observed_at=broker.get("last_probe_at"))


def redemptions(guardian: sqlite3.Connection, cutoff: str, labels: dict[str, str], credit_ids: Credits) -> None:
    """Export existing redemption receipts and bounded event summaries."""
    rows = cast("Iterator[sqlite3.Row]", guardian.execute(
        "SELECT * FROM redemption_attempts WHERE started_at < ? ORDER BY started_at", (cutoff,),
    ))
    for row in rows:
        account = labels[cast("str", row["account_label"])]
        fields = {key: cast("Json", row[key]) for key in REDEMPTION_FIELDS}
        emit("redemption", account=account,
             credit=credit_alias(credit_ids, account, cast("str", row["credit_ref"])), **fields)
    events = cast("Iterator[sqlite3.Row]", guardian.execute(
        "SELECT event_type, severity, COUNT(*) AS n, MIN(occurred_at) AS first_at, "
        "MAX(occurred_at) AS last_at FROM events WHERE occurred_at < ? GROUP BY 1,2", (cutoff,),
    ))
    for row in events:
        emit("guardian_event_summary", **cast("Record", dict(row)))


def plans(labels: dict[str, str]) -> None:
    """Project current overwritten plan fields, explicitly marked nonhistorical."""
    for directory in sorted(Path("/srv/auth-token-server/data/accounts").iterdir()):
        if not directory.is_dir():
            continue
        metadata = cast("Record", json.loads((directory / "metadata.json").read_text(encoding="utf-8")))
        state = cast("Record", json.loads((directory / "state.json").read_text(encoding="utf-8")))
        account = labels[cast("str", metadata["label"])]
        usage = cast("Record", state.get("usage") or {})
        emit("current_plan_observation", account=account, provider_observed_at=state.get("last_probe_at"),
             plan_type=usage.get("plan_type"), metadata_created_at=metadata.get("created_at"),
             observation_scope="current overwritten broker state; not historical plan proof")


def main() -> None:
    """Export durable samples, guardian observations and known redemptions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutoff", required=True, help="Exclusive ISO UTC cutoff")
    cutoff = cast("str", parser.parse_args().cutoff)
    with closing(database("/srv/codex-usage-dashboard/usage-history.sqlite3")) as quota, closing(
        database("/var/lib/pitchai-auth-reset-guardian/audit.sqlite3"),
    ) as guardian:
        aliases, labels = account_aliases(quota, cutoff)
        emit("manifest", cutoff=cutoff, accounts=len(aliases), schema=1,
             extracted_at=datetime.datetime.now(datetime.UTC).isoformat(),
             identity_rule="durable reference order; exact guardian-label join",
             cutoff_rule="row capture time strictly before cutoff")
        samples(quota, cutoff, aliases)
        credit_ids: Credits = {}
        snapshots(guardian, cutoff, labels, credit_ids)
        redemptions(guardian, cutoff, labels, credit_ids)
        plans(labels)


if __name__ == "__main__":
    main()
