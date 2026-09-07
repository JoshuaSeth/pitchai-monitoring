# Copyright (c) 2026 PitchAI. All rights reserved.
"""Export anonymous cohort tables and validation from a read-only ledger.

The output contains no raw session IDs, paths or account identities. CSV tables
retain exclusions and sensitivity variants so readers can choose other cohorts.
Every file hash and the exact SQL hash are included in the final manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import cast

_TABLES = {
    "account_months": "SELECT * FROM account_months ORDER BY account,month,strict_eligible",
    "bank_losses": "SELECT * FROM bank_losses ORDER BY account,credit",
    "epochs": "SELECT * FROM epochs ORDER BY account,segment",
    "epoch_exposures": "SELECT * FROM epoch_exposures ORDER BY account,segment,strict_eligible,model,effort",
    "hour_windows": "SELECT * FROM hour_windows ORDER BY interval_id",
    "exposures": "SELECT * FROM exposures ORDER BY interval_id,timing_scope,strict_eligible,model,effort",
    "hourly_analysis": "SELECT * FROM hourly_analysis ORDER BY interval_id",
    "epoch_analysis": "SELECT * FROM epoch_analysis ORDER BY account,segment",
    "cohort_validation": "SELECT * FROM cohort_validation ORDER BY check_name",
}


def export(connection: sqlite3.Connection, table: str, output: Path) -> dict[str, object]:
    """Export one named analysis table with deterministic ordering.

    Returns:
        File metadata and row count for the reproducibility manifest.
    """
    cursor = connection.execute(_TABLES[table])
    fields = [str(column[0]) for column in cursor.description]
    path = output / (table + ".csv")
    rows = 0
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        for row in cast("list[tuple[object, ...]]", cursor.fetchall()):
            writer.writerow(row)
            rows += 1
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": path.name, "rows": rows, "sha256": digest, "columns": fields}


def main() -> None:
    """Validate and export one existing ledger, without replacing old outputs.

    Raises:
        ValueError: If a cohort integrity check fails.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    database, output = cast("Path", args.database), cast("Path", args.output)
    sql = Path(__file__).with_name("analysis_views.sql").read_bytes()
    output.mkdir(exist_ok=False, parents=True)
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        connection.executescript(sql.decode())
        failed = cast("list[tuple[str, int]]", connection.execute(
            "SELECT * FROM cohort_validation WHERE failures<>0",
        ).fetchall())
        if failed:
            message = "Cohort integrity failure: " + json.dumps(failed)
            raise ValueError(message)
        files: list[dict[str, object]] = []
        for table in _TABLES:
            metadata = export(connection, table, output)
            files.append(metadata)
            sys.stdout.write(json.dumps(metadata) + "\n")
            sys.stdout.flush()
        manifest = {
            "schema": 1, "database_name": database.name, "sql_sha256": hashlib.sha256(sql).hexdigest(),
            "files": files, "status": "complete", "scope": "observed_recovered_workload",
            "qualification": "API reference value is not a subscription bill or hidden-credit reading.",
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
