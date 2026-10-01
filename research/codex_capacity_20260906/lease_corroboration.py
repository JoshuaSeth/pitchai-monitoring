# Copyright (c) 2026 PitchAI. All rights reserved.
"""Cross-check epoch-attributed calls against recorded historical lease ranges.

Renewals with the same account, affinity, client and issuance are one issuance.
The latest recorded expiry is an outer bound, not proof of uninterrupted
occupancy. Missing log timestamps and possible early releases prevent stronger
attribution. Lease evidence never overwrites the independent reset-epoch join.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import cast

_SCHEMA = """
CREATE TABLE links(cell TEXT,source TEXT,affinity TEXT,client TEXT,PRIMARY KEY(cell,source,affinity,client));
CREATE TABLE lease_states(account TEXT,affinity TEXT,client TEXT,issued REAL,expires REAL,
                         PRIMARY KEY(account,affinity,client,issued,expires));
"""
_ANALYSIS = """
CREATE TABLE leases AS SELECT account,affinity,client,issued,MAX(expires) AS expires,COUNT(*) AS states
  FROM lease_states GROUP BY account,affinity,client,issued;
CREATE INDEX lease_affinity ON leases(affinity,client,issued,expires);
CREATE TABLE matches AS
SELECT c.call_key,c.account,c.day,c.model,c.effort,c.strict_eligible,c.standard_usd,
       COUNT(DISTINCT l.affinity) AS affinities,COUNT(DISTINCT s.account) AS candidate_accounts,
       MAX(s.account=c.account) AS matching_account
FROM usage.account_calls c LEFT JOIN links l ON c.source=l.source AND c.cell=l.cell
LEFT JOIN leases s ON l.affinity=s.affinity AND l.client=s.client
                 AND c.timestamp>=s.issued AND c.timestamp<=s.expires
GROUP BY c.call_key;
CREATE TABLE summary AS
SELECT account,day,strict_eligible,
       CASE WHEN affinities=0 THEN 'no_source_affinity_link'
            WHEN candidate_accounts=0 THEN 'no_recorded_lease_range_at_call_time'
            WHEN candidate_accounts=1 AND matching_account=1 THEN 'one_compatible_recorded_account'
            WHEN matching_account=1 THEN 'multiple_compatible_recorded_accounts'
            ELSE 'only_other_accounts_in_recorded_ranges' END AS lease_grade,
       COUNT(*) AS calls,SUM(standard_usd) AS standard_usd
FROM matches GROUP BY account,day,strict_eligible,lease_grade;
"""


def load_affinities(connection: sqlite3.Connection, path: Path) -> None:
    """Import complete allowlisted source-affinity captures.

    Raises:
        ValueError: If an extraction is missing its manifest or completion.
    """
    cell: object = None
    complete = False
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = cast("dict[str, object]", json.loads(line))
            if row["kind"] == "affinity_manifest":
                cell = row["cell"]
            elif row["kind"] == "affinity_complete":
                complete = True
            elif row["kind"] == "source_affinity":
                connection.execute("INSERT INTO links VALUES (?,?,?,?)",
                                   (cell, row["source"], row["affinity"], row["client"]))
    if not cell or not complete:
        message = "Incomplete source-affinity capture"
        raise ValueError(message)


def load_leases(connection: sqlite3.Connection, path: Path) -> int:
    """Collapse only exact lease-state copies across the frozen recovery inputs.

    Returns:
        The number of source lease observations inspected.
    """
    observations = 0
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = cast("dict[str, object]", json.loads(line))
            if row["kind"] == "lease_observation":
                connection.execute("""
                    INSERT OR IGNORE INTO lease_states VALUES (?,?,?,?,?)
                """, (row["account"], row["affinity"], row["client"],
                      datetime.fromisoformat(cast("str", row["issued_at"])).timestamp(),
                      datetime.fromisoformat(cast("str", row["expires_at"])).timestamp()))
                observations += 1
    return observations


def main() -> None:
    """Write anonymous aggregate corroboration and its exact input hashes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database, evidence = cast("Path", args.database), cast("Path", args.evidence)
    inputs: dict[str, str] = {}
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.executescript(_SCHEMA)
        observations = 0
        for path in sorted(evidence.glob("*.jsonl.gz")):
            if path.name.startswith("source-affinities"):
                load_affinities(connection, path)
            elif path.name.startswith("recovery"):
                observations += load_leases(connection, path)
            else:
                continue
            with path.open("rb") as stream:
                inputs[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        connection.execute("ATTACH DATABASE ? AS usage", (f"file:{database}?mode=ro",))
        connection.executescript(_ANALYSIS)
        connection.row_factory = sqlite3.Row
        rows = cast("list[sqlite3.Row]", connection.execute("SELECT * FROM summary ORDER BY 1,2,3").fetchall())
        counts = cast("tuple[int, int, int]", connection.execute("""
            SELECT (SELECT COUNT(*) FROM leases),(SELECT COUNT(*) FROM lease_states),
                   (SELECT COUNT(*) FROM matches)
        """).fetchone())
        result = {
            "schema": 1, "source_lease_observations": observations, "distinct_issuances": counts[0],
            "distinct_renewal_states": counts[1], "account_calls_checked": counts[2],
            "inputs": inputs, "summary": [dict(row) for row in rows],
            "qualification": "Recorded issue-to-latest-expiry ranges are compatible evidence only. "
                             "Renewals overlap, early release is possible, and log timestamps are absent. "
                             "Neither missing nor conflicting ranges independently overturn an epoch attribution.",
        }
        with cast("Path", args.output).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
