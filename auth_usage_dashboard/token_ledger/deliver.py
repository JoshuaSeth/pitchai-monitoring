# Copyright (c) 2026 PitchAI. All rights reserved.
"""Ship changed node rows to the master fleet store.

Master ingests in-process. Workers pipe NDJSON to master over ssh with a
dedicated key whose ``authorized_keys`` entry is a ``restrict``ed forced
command, so the key can do nothing but ingest for its own node.
"""

from __future__ import annotations

import io
import json
import os
import select
import shutil
import signal
import time
from contextlib import closing, suppress
from typing import TYPE_CHECKING, cast

from .fleet_store import DEFAULT_FLEET_DB, connect_fleet, ingest

if TYPE_CHECKING:
    from pathlib import Path

    from .json_types import JsonObject, JsonValue
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


def _spawn_with_pipes(command: list[str]) -> tuple[int, int, int]:
    """Start ``command`` (fixed argv, no shell) with its stdin and stdout on pipes.

    Returns:
        The process id and the parent ends of the stdin and stdout pipes.
    """
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    actions = [
        (os.POSIX_SPAWN_DUP2, stdin_read, 0),
        (os.POSIX_SPAWN_DUP2, stdout_write, 1),
        (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0),
    ]
    try:
        process_id = os.posix_spawn(command[0], command, os.environ, file_actions=actions, setsid=True)
    finally:
        os.close(stdin_read)
        os.close(stdout_write)
    return process_id, stdin_write, stdout_read


def _collect_output(process_id: int, stdin_write: int, stdout_read: int, payload: bytes) -> tuple[int, bytes]:
    """Feed ``payload``, read stdout until EOF or the deadline, and reap the process.

    Returns:
        The exit code and everything the process wrote to stdout.
    """
    deadline = time.monotonic() + _SSH_TIMEOUT_SECONDS
    with suppress(BrokenPipeError), os.fdopen(stdin_write, "wb") as sink:
        sink.write(payload)
    chunks: list[bytes] = []
    with os.fdopen(stdout_read, "rb", buffering=0) as source:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([source], [], [], max(0.0, deadline - time.monotonic()))
            chunk = source.read(65_536) if ready else b""
            if not chunk:
                break
            chunks.append(chunk)
    if time.monotonic() >= deadline:
        with suppress(OSError):
            os.killpg(process_id, signal.SIGKILL)
    _, status = os.waitpid(process_id, 0)
    return os.waitstatus_to_exitcode(status), b"".join(chunks)


def _ssh_send(config: NodeConfig, payload: str) -> JsonObject:
    ssh = shutil.which("ssh") or "/usr/bin/ssh"
    command = [
        ssh,
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
    encoded = payload.encode()
    process_id, stdin_write, stdout_read = _spawn_with_pipes(command)
    exit_code, output = _collect_output(process_id, stdin_write, stdout_read, encoded)
    if exit_code != 0:
        message = f"ssh ingest failed with exit {exit_code}"
        raise RuntimeError(message)
    lines = output.decode("utf-8", errors="replace").strip().splitlines()
    reply = cast("JsonValue", json.loads(lines[-1] if lines else "null"))
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
