# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the fleet token ledger rollout reader, collection and delivery."""

from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from ._timeseries_test_fixtures import check, check_equal
from .token_ledger import rollout as rollout_module
from .token_ledger.collect import CollectHooks, collect
from .token_ledger.deliver import deliver
from .token_ledger.fleet_store import connect_fleet, ingest
from .token_ledger.node_store import NodeStore
from .token_ledger.rollout import FileState, read_new_lines, usage_delta
from .token_ledger.sources import Home, Lane, LaneIndex, NodeConfig

if TYPE_CHECKING:
    from pathlib import Path

    from .timeseries_types import JsonObject, SqlValue

HOUR = 3_600
BASE = 1_791_158_400  # 2026-10-05T00:00:00Z
THREAD = "01a0f87a-3bb8-7551-9b14-54e3388ef9bd"
CLAUDE_THREAD = "fe6e7f2f-c04e-47ad-905f-d651b302355f"
CONFIG = NodeConfig(
    node="master",
    cells=(),
    delivery="local",
    backfill_days=30,
    max_bytes=64 * 1024 * 1024,
    max_seconds=60.0,
)


def _line(kind: str, payload: JsonObject, epoch: float) -> str:
    stamp = datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")
    return json.dumps({"timestamp": stamp, "type": kind, "payload": payload}, separators=(",", ":")) + "\n"


def _meta(thread: str, epoch: float, cwd: str = "/work/lane") -> str:
    return _line(
        "session_meta",
        {"id": thread, "cwd": cwd, "model_provider": "openai", "base_instructions": {"text": "x" * 50}},
        epoch,
    )


def _turn(model: str, epoch: float) -> str:
    return _line("turn_context", {"turn_id": "t", "model": model, "effort": "high"}, epoch)


def _cumulative(epoch: float, inp: int, cached: int, out: int) -> str:
    total: JsonObject = {
        "input_tokens": inp,
        "cached_input_tokens": cached,
        "output_tokens": out,
        "reasoning_output_tokens": 0,
        "total_tokens": inp + out,
    }
    info: JsonObject = {"total_token_usage": total, "last_token_usage": total}
    return _line("event_msg", {"type": "token_count", "info": info, "rate_limits": None}, epoch)


def _write(path: Path, text: str, *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        handle.write(text)


def _rows(store: NodeStore) -> list[tuple[SqlValue, ...]]:
    cursor = store.connection.execute(
        "select hour_epoch, project, agent, provider, model, route, input, cached_input, output, total, requests "
        "from hourly order by hour_epoch, model",
    )
    return cast("list[tuple[SqlValue, ...]]", cursor.fetchall())


def _hooks(homes: list[Home], lanes: LaneIndex) -> CollectHooks:
    return CollectHooks(home_finder=lambda _config: homes, lane_loader=lambda _config: (lanes, []))


def _lanes() -> LaneIndex:
    index = LaneIndex()
    index.by_thread[THREAD] = Lane("dev-main-cell-one", "dft-lane", "dft", "Driestar DFT")
    index.by_worktree["/work/claude"] = Lane("dev-main-cell-one", "claude-lane", "potaito", None)
    return index


def test_cumulative_deltas_skip_repeats_and_survive_counter_reset() -> None:
    """Prove cumulative deltas skip repeats and survive counter reset."""
    state = FileState()
    first: JsonObject = {
        "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 5, "total_tokens": 105},
    }
    check_equal(usage_delta(state, first), (100, 40, 5, 0, 105), "first cumulative total is counted whole")
    check(usage_delta(state, first) is None, "a repeated cumulative total is skipped")
    second: JsonObject = {
        "total_token_usage": {"input_tokens": 160, "cached_input_tokens": 90, "output_tokens": 9, "total_tokens": 169},
    }
    check_equal(usage_delta(state, second), (60, 50, 4, 0, 64), "a higher total counts only the delta")
    reset: JsonObject = {
        "total_token_usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1, "total_tokens": 11},
    }
    check_equal(usage_delta(state, reset), (10, 0, 1, 0, 11), "a lower total is a counter reset")
    claude: JsonObject = {
        "last_token_usage": {"input_tokens": 7, "cached_input_tokens": 3, "output_tokens": 2, "total_tokens": 9},
    }
    check_equal(usage_delta(FileState(), claude), (7, 3, 2, 0, 9), "per-request usage is counted as is")


def test_reader_keeps_partial_lines_and_ignores_content_mentions(tmp_path: Path) -> None:
    """Prove reader keeps partial lines and ignores content mentions."""
    rollout = tmp_path / "r.jsonl"
    # Mentions the usage marker inside tool output; it must not be parsed as usage.
    noise = _line("response_item", {"type": "function_call_output", "output": '"payload":{"type":"token_count"'}, BASE)
    complete = _meta(THREAD, BASE) + _turn("gpt-6-astra", BASE) + noise + _cumulative(BASE + 10, 100, 0, 10)
    _write(rollout, complete + '{"timestamp":"2026-10-05T00:00:20Z","type":"event_msg","payload":{"type":"tok')
    state = FileState()
    with rollout.open("rb") as handle:
        result = read_new_lines(handle, state, budget=1 << 20)
    check_equal(state.offset, len(complete.encode()), "the cursor stops before the partial line")
    found = [(event.model, event.usage) for event in result.events]
    check_equal(found, [("gpt-6-astra", (100, 0, 10, 0, 110))], "only the real token count is an event")
    check_equal(state.thread_id, THREAD, "the session thread id is kept")


def test_reader_respects_byte_budget_on_line_boundaries(tmp_path: Path) -> None:
    """Prove reader respects byte budget on line boundaries."""
    rollout = tmp_path / "r.jsonl"
    indexes = range(5)
    lines = [_cumulative(BASE + index, 100 * (index + 1), 0, index + 1) for index in indexes]
    _write(rollout, "".join(lines))
    state = FileState()
    with rollout.open("rb") as handle:
        first = read_new_lines(handle, state, budget=len(lines[0]) + 1)
        check_equal(len(first.events), 2, "the budget is exceeded only to finish a line")
        second = read_new_lines(handle, state, budget=1 << 20)
    check_equal(len(second.events), 3, "the next read resumes at the cursor")
    check_equal(state.offset, rollout.stat().st_size, "the cursor reaches the end of the file")


def test_collect_counts_each_request_exactly_once_across_runs(tmp_path: Path) -> None:
    """Prove collect counts each request exactly once across runs."""
    codex = Home(str(tmp_path / "codex"), "codex_account")
    claude = Home(str(tmp_path / "claude"), "claude_code")
    codex_file = tmp_path / "codex/sessions/2026/10/05" / f"rollout-2026-10-05T00-00-00-{THREAD}.jsonl"
    claude_file = tmp_path / "claude/sessions/2026/10/05" / f"rollout-2026-10-05T00-00-00-{CLAUDE_THREAD}.jsonl"
    repeated = _cumulative(BASE + 60, 1000, 600, 50) + _cumulative(BASE + 61, 1000, 600, 50)
    _write(codex_file, _meta(THREAD, BASE) + _turn("gpt-6-astra", BASE) + repeated)
    last: JsonObject = {"input_tokens": 500, "cached_input_tokens": 400, "output_tokens": 20, "total_tokens": 520}
    usage: JsonObject = {"type": "token_count", "info": {"last_token_usage": last}, "rate_limits": None}
    per_turn = _line("event_msg", usage, BASE + HOUR + 5)
    _write(claude_file, _meta(CLAUDE_THREAD, BASE, cwd="/work/claude") + _turn("opus", BASE) + per_turn)
    store = NodeStore(tmp_path / "state/ledger.sqlite3")
    hooks = _hooks([codex, claude], _lanes())
    collect(CONFIG, store, now=BASE + 2 * HOUR, hooks=hooks)
    collect(CONFIG, store, now=BASE + 2 * HOUR, hooks=hooks)
    expected = [
        (BASE, "dft", "dft-lane", "openai", "gpt-6-astra", "codex_account", 1000, 600, 50, 1050, 1),
        (BASE + HOUR, "potaito", "claude-lane", "anthropic", "claude-opus", "claude_code", 500, 400, 20, 520, 1),
    ]
    check_equal(_rows(store), expected, "two runs store every request once, attributed to its lane")
    _write(codex_file, _cumulative(BASE + HOUR + 10, 1500, 1000, 70), append=True)
    collect(CONFIG, store, now=BASE + 2 * HOUR, hooks=hooks)
    rows = _rows(store)
    appended = (BASE + HOUR, "dft", "dft-lane", "openai", "gpt-6-astra", "codex_account", 500, 400, 20, 520, 1)
    check(appended in rows, "an appended cumulative total adds only its delta")
    check_equal(len(rows), 3, "the appended delta lands in its own hour")
    store.close()


def test_collect_skips_old_files_and_counts_only_inside_the_horizon(tmp_path: Path) -> None:
    """Prove collect skips old files and counts only inside the horizon."""
    home = Home(str(tmp_path / "codex"), "codex_account")
    old = tmp_path / "codex/sessions/2026/08/01/rollout-old-00000000-0000-0000-0000-000000000000.jsonl"
    live = tmp_path / "codex/sessions/2026/09/01/rollout-live-11111111-1111-1111-1111-111111111111.jsonl"
    _write(old, _cumulative(BASE - 60 * 86_400, 10, 0, 1))
    os.utime(old, (BASE - 60 * 86_400, BASE - 60 * 86_400))
    _write(live, _cumulative(BASE - 40 * 86_400, 100, 0, 1) + _cumulative(BASE - 60, 150, 0, 2))
    store = NodeStore(tmp_path / "ledger.sqlite3")
    summary = collect(CONFIG, store, now=BASE, hooks=_hooks([home], LaneIndex()))
    check_equal(summary.files_read, 1, "a file untouched since before the horizon is skipped")
    expected = [(BASE - HOUR, "_nonlane", "-", "openai", "unknown", "codex_account", 50, 0, 1, 51, 1)]
    check_equal(_rows(store), expected, "only the delta inside the horizon is counted")
    store.close()


def test_local_delivery_is_idempotent_and_pins_the_node(tmp_path: Path) -> None:
    """Prove local delivery is idempotent and pins the node."""
    home = Home(str(tmp_path / "codex"), "codex_account")
    rollout = tmp_path / "codex/sessions/2026/10/05" / f"rollout-x-{THREAD}.jsonl"
    _write(rollout, _meta(THREAD, BASE) + _turn("gpt-5.6-sol", BASE) + _cumulative(BASE + 1, 10, 0, 1))
    store = NodeStore(tmp_path / "ledger.sqlite3")
    fleet = tmp_path / "fleet.sqlite3"
    collect(CONFIG, store, now=BASE + 60, hooks=_hooks([home], _lanes()))
    check_equal(deliver(CONFIG, store, version="test", fleet_db=fleet)["rows"], 1, "the first delivery sends the row")
    check_equal(deliver(CONFIG, store, version="test", fleet_db=fleet)["rows"], 0, "a second delivery sends nothing")
    connection = connect_fleet(fleet)
    replay = '{"kind":"header"}\n' + json.dumps(next(iter(store.rows_since(0, 10)))) + "\n"
    ingest(connection, "jeff-dev", io.StringIO(replay))
    ingest(connection, "jeff-dev", io.StringIO(replay))
    cursor = connection.execute("select node, total from token_usage_hourly order by node")
    nodes = cast("list[tuple[str, int]]", cursor.fetchall())
    check_equal(nodes, [("jeff-dev", 11), ("master", 11)], "a replayed batch overwrites its own node's row")
    with pytest.raises(ValueError, match="aligned"):
        ingest(connection, "jeff-dev", io.StringIO('{"hour_epoch": 5, "cell": "x"}\n'))
    with pytest.raises(ValueError, match="node"):
        ingest(connection, "../evil", io.StringIO(""))
    connection.close()
    store.close()


def test_horizon_seek_counts_only_window_deltas_with_restored_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove horizon seek counts only window deltas with restored model."""
    monkeypatch.setattr(rollout_module, "_SEEK_MIN_BYTES", 1_000)
    monkeypatch.setattr(rollout_module, "_SEEK_PRECISION", 256)
    monkeypatch.setattr(rollout_module, "_PRIMER_BYTES", 3_000)
    start = BASE - 10 * 86_400
    indexes = range(400)
    events = [_cumulative(start + index * 2_000, 1_000 * (index + 1), 0, index + 1) for index in indexes]
    horizon = BASE - 10 * 86_400 + 300 * 2_000 - 1
    rollout = tmp_path / "big.jsonl"
    _write(rollout, "".join([_meta(THREAD, start), _turn("gpt-5.6-terra", start), *events]))
    state = FileState(count_from=horizon)
    with rollout.open("rb") as handle:
        rollout_module.prime_for_horizon(handle, rollout.stat().st_size, state)
        check(0 < state.offset < rollout.stat().st_size // 2 * 2, "the cursor starts inside the file")
        result = read_new_lines(handle, state, budget=1 << 30)
    check_equal(state.thread_id, THREAD, "the session header is restored")
    check_equal({event.model for event in result.events}, {"gpt-5.6-terra"}, "the turn model is restored")
    input_total = sum(event.usage[0] for event in result.events)
    check_equal(input_total, 100 * 1_000, "only deltas inside the window are counted")
    output_total = sum(event.usage[2] for event in result.events)
    check_equal(output_total, sum(range(301, 401)) - sum(range(300, 400)), "the cumulative baseline is primed")
