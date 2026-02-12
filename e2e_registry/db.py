from __future__ import annotations

import json
import os
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from e2e_registry.settings import RegistrySettings


SCHEMA_VERSION = 3


def _utc_ts() -> float:
    return float(time.time())


def _uuid() -> str:
    return str(uuid.uuid4())


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _json_loads(s: Any) -> Any:
    if s is None:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(str(s))
    except Exception:
        return None


def _connect(path: str) -> sqlite3.Connection:
    p = str(path or "").strip()
    if not p:
        raise ValueError("Missing db_path")
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    # Best-effort: WAL improves concurrency for a single-host service.
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    return conn


def ensure_schema(settings: RegistrySettings) -> None:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
    finally:
        conn.close()


def _ensure_schema_conn(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);"
    )
    row = conn.execute("SELECT v FROM schema_meta WHERE k='version'").fetchone()
    cur = int(row["v"]) if row and row["v"] else 0
    if cur >= SCHEMA_VERSION:
        return

    if cur == 0:
        _apply_v1(conn)
        _apply_v2(conn)
        _apply_v3(conn)
        conn.execute("INSERT OR REPLACE INTO schema_meta (k, v) VALUES ('version', ?)", (str(SCHEMA_VERSION),))
        return

    if cur == 1:
        _apply_v2(conn)
        _apply_v3(conn)
        conn.execute("UPDATE schema_meta SET v=? WHERE k='version'", (str(SCHEMA_VERSION),))
        return

    if cur == 2:
        _apply_v3(conn)
        conn.execute("UPDATE schema_meta SET v=? WHERE k='version'", (str(SCHEMA_VERSION),))
        return

    raise RuntimeError(f"Unsupported schema version upgrade path cur={cur} target={SCHEMA_VERSION}")


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    except Exception:
        return False
    for r in rows:
        try:
            if str(r["name"]) == str(column):
                return True
        except Exception:
            continue
    return False


def _apply_v1(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          updated_at_ts REAL NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          token_hash TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          revoked_at_ts REAL,
          UNIQUE(token_hash)
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tests (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          base_url TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          disabled_reason TEXT,
          disabled_until_ts REAL,
          interval_seconds INTEGER NOT NULL DEFAULT 300,
          timeout_seconds INTEGER NOT NULL DEFAULT 45,
          jitter_seconds INTEGER NOT NULL DEFAULT 30,
          down_after_failures INTEGER NOT NULL DEFAULT 2,
          up_after_successes INTEGER NOT NULL DEFAULT 2,
          notify_on_recovery INTEGER NOT NULL DEFAULT 0,
          dispatch_on_failure INTEGER NOT NULL DEFAULT 0,
          definition_json TEXT NOT NULL,
          created_at_ts REAL NOT NULL,
          updated_at_ts REAL NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS test_state (
          test_id TEXT PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE,
          effective_ok INTEGER NOT NULL DEFAULT 1,
          fail_streak INTEGER NOT NULL DEFAULT 0,
          success_streak INTEGER NOT NULL DEFAULT 0,
          last_ok_ts REAL,
          last_fail_ts REAL,
          last_infra_ts REAL,
          last_alert_ts REAL,
          next_due_ts REAL,
          running_lock_id TEXT,
          running_locked_at_ts REAL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,
          test_id TEXT NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
          scheduled_for_ts REAL NOT NULL,
          started_at_ts REAL,
          finished_at_ts REAL,
          status TEXT NOT NULL, -- pass|fail|infra_degraded
          elapsed_ms REAL,
          error_kind TEXT,
          error_message TEXT,
          final_url TEXT,
          title TEXT,
          artifacts_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tests_tenant_enabled ON tests(tenant_id, enabled);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_state_due ON test_state(next_due_ts);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_test_started ON runs(test_id, started_at_ts DESC);")


def _apply_v2(conn: sqlite3.Connection) -> None:
    """
    v2 adds support for uploaded code-based tests in addition to StepFlow definitions.
    """
    # tests: identify how a test should be executed.
    if not _column_exists(conn, "tests", "test_kind"):
        conn.execute("ALTER TABLE tests ADD COLUMN test_kind TEXT NOT NULL DEFAULT 'stepflow';")
    if not _column_exists(conn, "tests", "source_relpath"):
        conn.execute("ALTER TABLE tests ADD COLUMN source_relpath TEXT;")
    if not _column_exists(conn, "tests", "source_filename"):
        conn.execute("ALTER TABLE tests ADD COLUMN source_filename TEXT;")
    if not _column_exists(conn, "tests", "source_sha256"):
        conn.execute("ALTER TABLE tests ADD COLUMN source_sha256 TEXT;")
    if not _column_exists(conn, "tests", "source_content_type"):
        conn.execute("ALTER TABLE tests ADD COLUMN source_content_type TEXT;")


def _apply_v3(conn: sqlite3.Connection) -> None:
    """
    v3 adds a lightweight log of dispatcher triage runs (agent conclusions) so the dashboard
    can show what the agent found during incidents.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dispatch_runs (
          id TEXT PRIMARY KEY,
          created_at_ts REAL NOT NULL,
          state_key TEXT NOT NULL,
          bundle TEXT,
          ui_url TEXT,
          queue_state TEXT,
          agent_message TEXT,
          error_message TEXT,
          context_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dispatch_runs_created_at ON dispatch_runs(created_at_ts DESC);")


@dataclass(frozen=True)
class AuthedTenant:
    tenant_id: str
    api_key_id: str


def db_now_ts() -> float:
    return _utc_ts()


def create_tenant(settings: RegistrySettings, *, name: str) -> dict[str, Any]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        tid = _uuid()
        now = _utc_ts()
        conn.execute(
            "INSERT INTO tenants (id, name, created_at_ts, updated_at_ts) VALUES (?, ?, ?, ?)",
            (tid, name.strip(), now, now),
        )
        return {"id": tid, "name": name.strip(), "created_at_ts": now}
    finally:
        conn.close()


def create_api_key(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    name: str,
    token_hash: str,
) -> dict[str, Any]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        kid = _uuid()
        now = _utc_ts()
        conn.execute(
            "INSERT INTO api_keys (id, tenant_id, name, token_hash, created_at_ts) VALUES (?, ?, ?, ?, ?)",
            (kid, tenant_id, name.strip(), token_hash, now),
        )
        return {"id": kid, "tenant_id": tenant_id, "name": name.strip(), "created_at_ts": now}
    finally:
        conn.close()


def get_api_key_by_hash(settings: RegistrySettings, *, token_hash: str) -> AuthedTenant | None:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        row = conn.execute(
            "SELECT id, tenant_id FROM api_keys WHERE token_hash=? AND revoked_at_ts IS NULL",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        return AuthedTenant(tenant_id=str(row["tenant_id"]), api_key_id=str(row["id"]))
    finally:
        conn.close()


def list_tests(settings: RegistrySettings, *, tenant_id: str) -> list[dict[str, Any]]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        rows = conn.execute(
            """
            SELECT
              t.*,
              s.effective_ok, s.fail_streak, s.success_streak, s.last_ok_ts, s.last_fail_ts, s.last_infra_ts,
              s.last_alert_ts, s.next_due_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            WHERE t.tenant_id=?
            ORDER BY t.created_at_ts DESC
            """,
            (tenant_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(dict(r))
        return out
    finally:
        conn.close()


def get_test(settings: RegistrySettings, *, tenant_id: str, test_id: str) -> dict[str, Any] | None:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        row = conn.execute(
            """
            SELECT
              t.*,
              s.effective_ok, s.fail_streak, s.success_streak, s.last_ok_ts, s.last_fail_ts, s.last_infra_ts,
              s.last_alert_ts, s.next_due_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            WHERE t.id=? AND t.tenant_id=?
            """,
            (test_id, tenant_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insert_test(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    name: str,
    base_url: str,
    test_id: str | None = None,
    test_kind: str = "stepflow",
    definition: dict[str, Any] | None = None,
    source_relpath: str | None = None,
    source_filename: str | None = None,
    source_sha256: str | None = None,
    source_content_type: str | None = None,
    interval_seconds: int,
    timeout_seconds: int,
    jitter_seconds: int,
    down_after_failures: int,
    up_after_successes: int,
    notify_on_recovery: bool,
    dispatch_on_failure: bool,
) -> dict[str, Any]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        now = _utc_ts()
        test_id = str(test_id).strip() if test_id is not None else _uuid()
        if not test_id:
            test_id = _uuid()
        jitter = max(0, int(jitter_seconds))
        next_due = now + float(random.randint(0, jitter)) if jitter else now
        kind = str(test_kind or "stepflow").strip().lower() or "stepflow"
        defn = definition if isinstance(definition, dict) else {}

        conn.execute("BEGIN IMMEDIATE;")
        try:
            conn.execute(
                """
                INSERT INTO tests (
                  id, tenant_id, name, base_url, enabled, interval_seconds, timeout_seconds, jitter_seconds,
                  down_after_failures, up_after_successes, notify_on_recovery, dispatch_on_failure,
                  test_kind, definition_json, source_relpath, source_filename, source_sha256, source_content_type,
                  created_at_ts, updated_at_ts
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test_id,
                    tenant_id,
                    name.strip(),
                    base_url.strip(),
                    int(interval_seconds),
                    int(timeout_seconds),
                    int(jitter_seconds),
                    int(down_after_failures),
                    int(up_after_successes),
                    1 if notify_on_recovery else 0,
                    1 if dispatch_on_failure else 0,
                    kind,
                    _json_dumps(defn),
                    str(source_relpath).strip() if source_relpath else None,
                    str(source_filename).strip() if source_filename else None,
                    str(source_sha256).strip() if source_sha256 else None,
                    str(source_content_type).strip() if source_content_type else None,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO test_state (
                  test_id, effective_ok, fail_streak, success_streak, last_ok_ts, last_fail_ts, last_infra_ts,
                  last_alert_ts, next_due_ts, running_lock_id, running_locked_at_ts
                ) VALUES (?, 1, 0, 0, NULL, NULL, NULL, NULL, ?, NULL, NULL)
                """,
                (test_id, float(next_due)),
            )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        return {
            "id": test_id,
            "tenant_id": tenant_id,
            "name": name.strip(),
            "base_url": base_url.strip(),
            "test_kind": kind,
            "source_relpath": str(source_relpath).strip() if source_relpath else None,
            "next_due_ts": next_due,
        }
    finally:
        conn.close()


def patch_test(settings: RegistrySettings, *, tenant_id: str, test_id: str, patch: dict[str, Any]) -> bool:
    """
    Partial update for test metadata/config. Only updates columns explicitly provided in patch.
    """
    allowed = {
        "name",
        "base_url",
        "definition",
        "interval_seconds",
        "timeout_seconds",
        "jitter_seconds",
        "down_after_failures",
        "up_after_successes",
        "notify_on_recovery",
        "dispatch_on_failure",
    }
    cleaned = {k: v for k, v in (patch or {}).items() if k in allowed}
    if not cleaned:
        return False

    sets: list[str] = []
    params: list[Any] = []

    if "name" in cleaned and cleaned["name"] is not None:
        sets.append("name=?")
        params.append(str(cleaned["name"]).strip())

    if "base_url" in cleaned and cleaned["base_url"] is not None:
        sets.append("base_url=?")
        params.append(str(cleaned["base_url"]).strip())

    if "definition" in cleaned and cleaned["definition"] is not None:
        sets.append("definition_json=?")
        params.append(_json_dumps(cleaned["definition"]))

    for k in ("interval_seconds", "timeout_seconds", "jitter_seconds", "down_after_failures", "up_after_successes"):
        if k in cleaned and cleaned[k] is not None:
            sets.append(f"{k}=?")
            params.append(int(cleaned[k]))

    for k in ("notify_on_recovery", "dispatch_on_failure"):
        if k in cleaned and cleaned[k] is not None:
            sets.append(f"{k}=?")
            params.append(1 if bool(cleaned[k]) else 0)

    if not sets:
        return False

    now = _utc_ts()
    sets.append("updated_at_ts=?")
    params.append(now)
    params.extend([test_id, tenant_id])

    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        res = conn.execute(
            f"UPDATE tests SET {', '.join(sets)} WHERE id=? AND tenant_id=?",
            tuple(params),
        )
        return int(res.rowcount or 0) > 0
    finally:
        conn.close()


def update_test_source(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    source_relpath: str,
    source_filename: str,
    source_sha256: str | None,
    source_content_type: str | None,
) -> bool:
    """
    Update the stored test source pointer for code-based tests.
    """
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        now = _utc_ts()
        res = conn.execute(
            """
            UPDATE tests
            SET source_relpath=?, source_filename=?, source_sha256=?, source_content_type=?, updated_at_ts=?
            WHERE id=? AND tenant_id=?
            """,
            (
                str(source_relpath).strip(),
                str(source_filename).strip(),
                str(source_sha256).strip() if source_sha256 else None,
                str(source_content_type).strip() if source_content_type else None,
                now,
                test_id,
                tenant_id,
            ),
        )
        return int(res.rowcount or 0) > 0
    finally:
        conn.close()


def get_test_config_internal(settings: RegistrySettings, *, test_id: str) -> dict[str, Any] | None:
    """
    Internal helper for alerts/runner paths (not tenant-auth checked).
    """
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        row = conn.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_test_disabled(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    test_id: str,
    disabled: bool,
    reason: str | None,
    until_ts: float | None,
) -> bool:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        now = _utc_ts()
        if not disabled:
            enabled = 1
            until_ts2 = None
            reason2 = None
        else:
            # Temporary disable if until_ts is in the future; otherwise treat as permanent disable.
            if until_ts is not None and float(until_ts) > now:
                enabled = 1
                until_ts2 = float(until_ts)
            else:
                enabled = 0
                until_ts2 = None
            reason2 = reason.strip() if reason else None
        res = conn.execute(
            """
            UPDATE tests
            SET enabled=?, disabled_reason=?, disabled_until_ts=?, updated_at_ts=?
            WHERE id=? AND tenant_id=?
            """,
            (
                enabled,
                reason2,
                until_ts2,
                now,
                test_id,
                tenant_id,
            ),
        )
        return int(res.rowcount or 0) > 0
    finally:
        conn.close()


def trigger_run_now(settings: RegistrySettings, *, tenant_id: str, test_id: str) -> bool:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        now = _utc_ts()
        res = conn.execute(
            """
            UPDATE test_state
            SET next_due_ts=?
            WHERE test_id IN (SELECT id FROM tests WHERE id=? AND tenant_id=?)
            """,
            (now, test_id, tenant_id),
        )
        return int(res.rowcount or 0) > 0
    finally:
        conn.close()


def list_runs(settings: RegistrySettings, *, tenant_id: str, test_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        rows = conn.execute(
            """
            SELECT r.*
            FROM runs r
            JOIN tests t ON t.id=r.test_id
            WHERE r.test_id=? AND t.tenant_id=?
            ORDER BY r.scheduled_for_ts DESC
            LIMIT ?
            """,
            (test_id, tenant_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run(settings: RegistrySettings, *, tenant_id: str, run_id: str) -> dict[str, Any] | None:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        row = conn.execute(
            """
            SELECT r.*, t.tenant_id, t.name AS test_name, t.base_url AS test_base_url
            FROM runs r
            JOIN tests t ON t.id=r.test_id
            WHERE r.id=? AND t.tenant_id=?
            """,
            (run_id, tenant_id),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _update_effective_ok(
    *,
    prev_effective_ok: bool,
    observed_ok: bool,
    fail_streak: int,
    success_streak: int,
    down_after_failures: int,
    up_after_successes: int,
) -> tuple[bool, int, int, bool, bool]:
    """
    Returns: (next_effective_ok, next_fail_streak, next_success_streak, alerted_down, recovered_up)
    """
    down_after_failures = max(1, int(down_after_failures))
    up_after_successes = max(1, int(up_after_successes))

    if observed_ok:
        success_streak = int(success_streak) + 1
        fail_streak = 0
    else:
        fail_streak = int(fail_streak) + 1
        success_streak = 0

    if prev_effective_ok:
        next_effective_ok = not (fail_streak >= down_after_failures)
    else:
        next_effective_ok = bool(success_streak >= up_after_successes)

    alerted_down = bool(prev_effective_ok and not next_effective_ok)
    recovered_up = bool((not prev_effective_ok) and next_effective_ok)
    return next_effective_ok, fail_streak, success_streak, alerted_down, recovered_up


@dataclass(frozen=True)
class ClaimedRun:
    run_id: str
    test_id: str
    tenant_id: str
    test_name: str
    base_url: str
    timeout_seconds: int
    test_kind: str
    definition: dict[str, Any]
    source_relpath: str | None
    source_filename: str | None
    source_sha256: str | None


def claim_due_runs(settings: RegistrySettings, *, max_runs: int) -> list[ClaimedRun]:
    """
    Claim due tests and create run records, returning claimed runs for the runner.
    """
    max_runs = max(0, min(int(max_runs), 50))
    if max_runs <= 0:
        return []

    now = _utc_ts()
    lock_timeout = max(10, int(settings.runner_lock_timeout_seconds))
    lock_cutoff = now - float(lock_timeout)

    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        conn.execute("BEGIN IMMEDIATE;")
        try:
            rows = conn.execute(
                """
                SELECT
                  t.id AS test_id,
                  t.tenant_id AS tenant_id,
                  t.name AS test_name,
                  t.base_url AS base_url,
                  t.timeout_seconds AS timeout_seconds,
                  t.test_kind AS test_kind,
                  t.definition_json AS definition_json,
                  t.source_relpath AS source_relpath,
                  t.source_filename AS source_filename,
                  t.source_sha256 AS source_sha256,
                  s.next_due_ts AS next_due_ts,
                  s.running_lock_id AS running_lock_id,
                  s.running_locked_at_ts AS running_locked_at_ts
                FROM tests t
                JOIN test_state s ON s.test_id=t.id
                WHERE
                  t.enabled=1
                  AND (t.disabled_until_ts IS NULL OR t.disabled_until_ts <= ?)
                  AND (s.next_due_ts IS NULL OR s.next_due_ts <= ?)
                  AND (
                    s.running_lock_id IS NULL
                    OR s.running_locked_at_ts IS NULL
                    OR s.running_locked_at_ts < ?
                  )
                ORDER BY COALESCE(s.next_due_ts, 0) ASC, t.created_at_ts ASC
                LIMIT ?
                """,
                (now, now, lock_cutoff, max_runs),
            ).fetchall()

            claimed: list[ClaimedRun] = []
            for r in rows:
                run_id = _uuid()
                test_id = str(r["test_id"])
                conn.execute(
                    "UPDATE test_state SET running_lock_id=?, running_locked_at_ts=? WHERE test_id=?",
                    (run_id, now, test_id),
                )
                conn.execute(
                    """
                    INSERT INTO runs (
                      id, test_id, scheduled_for_ts, started_at_ts, finished_at_ts,
                      status, elapsed_ms, error_kind, error_message, final_url, title, artifacts_json
                    ) VALUES (?, ?, ?, NULL, NULL, 'infra_degraded', NULL, 'pending', NULL, NULL, NULL, '{}')
                    """,
                    (run_id, test_id, now),
                )
                claimed.append(
                    ClaimedRun(
                        run_id=run_id,
                        test_id=test_id,
                        tenant_id=str(r["tenant_id"]),
                        test_name=str(r["test_name"]),
                        base_url=str(r["base_url"]),
                        timeout_seconds=int(r["timeout_seconds"] or 45),
                        test_kind=str(r["test_kind"] or "stepflow").strip().lower() or "stepflow",
                        definition=_json_loads(r["definition_json"]) or {},
                        source_relpath=str(r["source_relpath"]).strip() if r["source_relpath"] else None,
                        source_filename=str(r["source_filename"]).strip() if r["source_filename"] else None,
                        source_sha256=str(r["source_sha256"]).strip() if r["source_sha256"] else None,
                    )
                )
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return claimed
    finally:
        conn.close()


@dataclass(frozen=True)
class RunCompletion:
    status: str  # pass|fail|infra_degraded
    elapsed_ms: float | None
    error_kind: str | None
    error_message: str | None
    final_url: str | None
    title: str | None
    artifacts: dict[str, Any]
    started_at_ts: float | None
    finished_at_ts: float | None


@dataclass(frozen=True)
class CompletionOutcome:
    updated: bool
    alerted_down: bool
    recovered_up: bool
    effective_ok: bool | None
    fail_streak: int | None
    success_streak: int | None
    tenant_id: str | None
    test_id: str | None
    test_name: str | None
    run_id: str | None


def complete_run(settings: RegistrySettings, *, run_id: str, completion: RunCompletion) -> CompletionOutcome:
    """
    Mark a run complete, clear the lock, reschedule, and update debounced effective state.
    Returns whether a DOWN transition was alerted (and/or recovered) so the caller can send notifications.
    """
    rid = str(run_id or "").strip()
    if not rid:
        return CompletionOutcome(
            updated=False,
            alerted_down=False,
            recovered_up=False,
            effective_ok=None,
            fail_streak=None,
            success_streak=None,
            tenant_id=None,
            test_id=None,
            test_name=None,
            run_id=None,
        )

    now = _utc_ts()
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        conn.execute("BEGIN IMMEDIATE;")
        try:
            row = conn.execute(
                """
                SELECT
                  r.id AS run_id,
                  r.test_id AS test_id,
                  t.tenant_id AS tenant_id,
                  t.name AS test_name,
                  t.interval_seconds AS interval_seconds,
                  t.jitter_seconds AS jitter_seconds,
                  t.down_after_failures AS down_after_failures,
                  t.up_after_successes AS up_after_successes,
                  s.effective_ok AS effective_ok,
                  s.fail_streak AS fail_streak,
                  s.success_streak AS success_streak
                FROM runs r
                JOIN tests t ON t.id=r.test_id
                JOIN test_state s ON s.test_id=t.id
                WHERE r.id=?
                """,
                (rid,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK;")
                return CompletionOutcome(
                    updated=False,
                    alerted_down=False,
                    recovered_up=False,
                    effective_ok=None,
                    fail_streak=None,
                    success_streak=None,
                    tenant_id=None,
                    test_id=None,
                    test_name=None,
                    run_id=rid,
                )

            test_id = str(row["test_id"])
            tenant_id = str(row["tenant_id"])
            test_name = str(row["test_name"])

            # Update run record.
            conn.execute(
                """
                UPDATE runs
                SET
                  started_at_ts=?,
                  finished_at_ts=?,
                  status=?,
                  elapsed_ms=?,
                  error_kind=?,
                  error_message=?,
                  final_url=?,
                  title=?,
                  artifacts_json=?
                WHERE id=?
                """,
                (
                    completion.started_at_ts,
                    completion.finished_at_ts,
                    str(completion.status),
                    completion.elapsed_ms,
                    completion.error_kind,
                    completion.error_message,
                    completion.final_url,
                    completion.title,
                    _json_dumps(completion.artifacts or {}),
                    rid,
                ),
            )

            # Clear lock.
            conn.execute(
                "UPDATE test_state SET running_lock_id=NULL, running_locked_at_ts=NULL WHERE test_id=?",
                (test_id,),
            )

            # Reschedule next due.
            interval_seconds = max(1, int(row["interval_seconds"] or 300))
            jitter_seconds = max(0, int(row["jitter_seconds"] or 0))
            jitter = float(random.randint(0, jitter_seconds)) if jitter_seconds else 0.0
            next_due = now + float(interval_seconds) + jitter
            conn.execute("UPDATE test_state SET next_due_ts=? WHERE test_id=?", (next_due, test_id))

            prev_effective = bool(int(row["effective_ok"] or 1))
            fail_streak = int(row["fail_streak"] or 0)
            success_streak = int(row["success_streak"] or 0)
            down_after = max(1, int(row["down_after_failures"] or 2))
            up_after = max(1, int(row["up_after_successes"] or 2))

            alerted_down = False
            recovered_up = False
            effective_ok_out: bool | None = None

            status = str(completion.status or "").strip().lower()
            if status == "infra_degraded":
                # Infra degraded runs should not change the test's effective OK state.
                conn.execute(
                    "UPDATE test_state SET last_infra_ts=? WHERE test_id=?",
                    (now, test_id),
                )
                effective_ok_out = prev_effective
            else:
                observed_ok = status == "pass"
                (
                    next_effective,
                    next_fail,
                    next_success,
                    alerted_down,
                    recovered_up,
                ) = _update_effective_ok(
                    prev_effective_ok=prev_effective,
                    observed_ok=observed_ok,
                    fail_streak=fail_streak,
                    success_streak=success_streak,
                    down_after_failures=down_after,
                    up_after_successes=up_after,
                )
                effective_ok_out = next_effective
                fail_streak = next_fail
                success_streak = next_success
                conn.execute(
                    """
                    UPDATE test_state
                    SET effective_ok=?, fail_streak=?, success_streak=?, last_ok_ts=?, last_fail_ts=?
                    WHERE test_id=?
                    """,
                    (
                        1 if next_effective else 0,
                        int(next_fail),
                        int(next_success),
                        now if observed_ok else None,
                        now if (not observed_ok) else None,
                        test_id,
                    ),
                )

            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return CompletionOutcome(
            updated=True,
            alerted_down=bool(alerted_down),
            recovered_up=bool(recovered_up),
            effective_ok=effective_ok_out,
            fail_streak=int(fail_streak),
            success_streak=int(success_streak),
            tenant_id=tenant_id,
            test_id=test_id,
            test_name=test_name,
            run_id=rid,
        )
    finally:
        conn.close()


def status_summary(settings: RegistrySettings) -> dict[str, Any]:
    """
    Lightweight summary intended for monitoring heartbeats and dashboards.
    """
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        rows = conn.execute(
            """
            SELECT
              t.id AS test_id,
              t.tenant_id AS tenant_id,
              t.name AS test_name,
              t.base_url AS base_url,
              t.test_kind AS test_kind,
              t.enabled AS enabled,
              s.effective_ok AS effective_ok,
              s.fail_streak AS fail_streak,
              s.success_streak AS success_streak,
              s.last_ok_ts AS last_ok_ts,
              s.last_fail_ts AS last_fail_ts,
              s.last_infra_ts AS last_infra_ts,
              s.next_due_ts AS next_due_ts,
              r.status AS last_status,
              r.elapsed_ms AS last_elapsed_ms,
              r.finished_at_ts AS last_finished_at_ts
            FROM tests t
            LEFT JOIN test_state s ON s.test_id=t.id
            LEFT JOIN runs r ON r.id = (
              SELECT r2.id FROM runs r2 WHERE r2.test_id=t.id ORDER BY r2.scheduled_for_ts DESC LIMIT 1
            )
            ORDER BY t.created_at_ts DESC
            """
        ).fetchall()

        tests = [dict(r) for r in rows]
        failing: list[dict[str, Any]] = []
        for t in tests:
            v = t.get("effective_ok")
            try:
                v_i = 1 if v is None else int(v)
            except Exception:
                v_i = 1
            if v_i == 0:
                failing.append(t)
        return {
            "ok": True,
            "total_tests": len(tests),
            "failing_tests": len(failing),
            "tests": tests[:200],
        }
    finally:
        conn.close()


def insert_dispatch_run(
    settings: RegistrySettings,
    *,
    state_key: str,
    bundle: str | None,
    ui_url: str | None,
    queue_state: str | None,
    agent_message: str | None,
    error_message: str | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        rid = _uuid()
        now = _utc_ts()
        conn.execute(
            """
            INSERT INTO dispatch_runs (
              id, created_at_ts, state_key, bundle, ui_url, queue_state, agent_message, error_message, context_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                now,
                str(state_key or "").strip(),
                (str(bundle).strip() if bundle is not None else None),
                (str(ui_url).strip() if ui_url is not None else None),
                (str(queue_state).strip() if queue_state is not None else None),
                (str(agent_message)[:20_000] if isinstance(agent_message, str) and agent_message.strip() else None),
                (str(error_message)[:5_000] if isinstance(error_message, str) and error_message.strip() else None),
                _json_dumps(context or {}),
            ),
        )
        return {
            "id": rid,
            "created_at_ts": now,
            "state_key": state_key,
            "bundle": bundle,
            "ui_url": ui_url,
            "queue_state": queue_state,
            "agent_message": agent_message,
            "error_message": error_message,
            "context": context or {},
        }
    finally:
        conn.close()


def list_dispatch_runs(settings: RegistrySettings, *, limit: int = 80) -> list[dict[str, Any]]:
    conn = _connect(settings.db_path)
    try:
        _ensure_schema_conn(conn)
        rows = conn.execute(
            """
            SELECT
              id,
              created_at_ts,
              state_key,
              bundle,
              ui_url,
              queue_state,
              agent_message,
              error_message,
              context_json
            FROM dispatch_runs
            ORDER BY created_at_ts DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["context"] = _json_loads(d.get("context_json")) or {}
            d.pop("context_json", None)
            out.append(d)
        return out
    finally:
        conn.close()
