# Copyright (c) 2026 PitchAI. All rights reserved.
"""Ship changed node rows to the master fleet store.

Master ingests in-process. Workers pipe NDJSON to master over ssh with a
dedicated key whose ``authorized_keys`` entry is a ``restrict``ed forced
command, so the key can do nothing but ingest for its own node.
"""

from __future__ import annotations

import io
import json
import subprocess
import time
from contextlib import closing
from typing import TYPE_CHECKING, cast

from .fleet_store import DEFAULT_FLEET_DB, connect_fleet, ingest

if TYPE_CHECKING:
    from pathlib import Path

    from auth_usage_dashboard.timeseries_types import JsonObject, JsonValue

    from .node_store import NodeStore
    from .sources import NodeConfig

BATCH_ROWS = 20_000
MAX_BATCHES_PER_RUN = 10
_SSH_TIMEOUT_SECONDS = 120


def _header(store: NodeStore, version: str) -> JsonObject:
    return {
        "kind": "header",
        "version": version,
        "collected_at": float(store.meta("last_collect_at", "0") or 0),
        "backlog_bytes": int(store.meta("backlog_bytes", "0") or 0),
        "files_tracked": int(store.meta("files_tracked", "0") or 0),
        "homes": int(store.meta("homes", "0") or 0),
        "lane_errors": store.meta("lane_errors", ""),
    }


def _ssh_send(config: NodeConfig, payload: str) -> JsonObject:
    command = [
        "ssh",
        "-i",
        config.ssh_key,
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        f"UserKnownHostsFile={config.known_hosts}",
        "-o",
        "StrictHostKeyChecking=yes",
        config.master,
        "token-ledger-ingest",
    ]
    # Fixed argv without a shell; the only remote command is the forced ``token-ledger-ingest``.
    completed = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        text=True,
        timeout=_SSH_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        message = f"ssh ingest failed with exit {completed.returncode}"
        raise RuntimeError(message)
    reply = cast("JsonValue", json.loads(completed.stdout.strip().splitlines()[-1]))
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        message = "ingest did not acknowledge the batch"
        raise RuntimeError(message)
    return reply


def _send(config: NodeConfig, payload: str, fleet_db: Path) -> JsonObject:
    if config.delivery != "local":
        return _ssh_send(config, payload)
    with closing(connect_fleet(fleet_db)) as connection:
        return ingest(connection, config.node, io.StringIO(payload))


def deliver(
    config: NodeConfig,
    store: NodeStore,
    *,
    version: str,
    fleet_db: Path = DEFAULT_FLEET_DB,
) -> JsonObject:
    """Send every row changed since the last acknowledged sequence.

    Returns:
        Rows sent, batches and the new acknowledged sequence.
    """
    acked = int(store.meta("acked_seq", "0") or 0)
    sent = batches = 0
    while batches < MAX_BATCHES_PER_RUN:
        rows = list(store.rows_since(acked, BATCH_ROWS))
        lines = [json.dumps(_header(store, version)), *(json.dumps(row) for row in rows)]
        payload = "\n".join(lines) + "\n"
        _send(config, payload, fleet_db)
        batches += 1
        sent += len(rows)
        if rows:
            highest = max(int(str(row["change_seq"])) for row in rows)
            # A full batch may split one change group: resend that group next batch.
            acked = highest - 1 if len(rows) == BATCH_ROWS and highest - 1 > acked else highest
            store.set_meta({"acked_seq": acked})
        store.set_meta({"last_push_at": time.time()})
        if len(rows) < BATCH_ROWS:
            break
    return {"rows": sent, "batches": batches, "acked_seq": acked}
