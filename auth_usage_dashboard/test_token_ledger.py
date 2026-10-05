# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof for the fleet token ledger exporter, delivery and report."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest

from .token_ledger.collect import collect
from .token_ledger.deliver import deliver
from .token_ledger.fleet_store import connect_fleet, ingest
from .token_ledger.node_store import NodeStore
from .token_ledger.report import build_report
from .token_ledger.rollout import FileState, read_new_lines, usage_delta
from .token_ledger.sources import Home, Lane, LaneIndex, NodeConfig

HOUR = 3_600
BASE = 1_791_158_400  # 2026-10-05T00:00:00Z
THREAD = "01a0f87a-3bb8-7551-9b14-54e3388ef9bd"
CLAUDE_THREAD = "fe6e7f2f-c04e-47ad-905f-d651b302355f"


def _stamp(epoch: float) -> str:
    from datetime import datetime, timezone  # noqa: PLC0415 - local helper import

    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _line(kind: str, payload: dict[str, object], epoch: float) -> str:
    return json.dumps({"timestamp": _stamp(epoch), "type": kind, "payload": payload}, separators=(",", ":")) + "\n"


def _meta(thread: str, epoch: float, cwd: str = "/work/lane") -> str:
    return _line("session_meta", {"id": thread, "cwd": cwd, "model_provider": "openai", "base_instructions": {"text": "x" * 50}}, epoch)


def _turn(model: str, epoch: float) -> str:
    return _line("turn_context", {"turn_id": "t", "model": model, "effort": "high"}, epoch)


def _cumulative(epoch: float, inp: int, cached: int, out: int) -> str:
    total = {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out, "reasoning_output_tokens": 0, "total_tokens": inp + out}
    return _line("event_msg", {"type": "token_count", "info": {"total_token_usage": total, "last_token_usage": total}, "rate_limits": None}, epoch)


def _last(epoch: float, inp: int, cached: int, out: int) -> str:
    last = {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out, "total_tokens": inp + out}
    return _line("event_msg", {"type": "token_count", "info": {"last_token_usage": last}, "rate_limits": None}, epoch)


def _noise(epoch: float) -> str:
    # Mentions the marker inside content; must not be parsed as usage.
    return _line("response_item", {"type": "function_call_output", "output": '"payload":{"type":"token_count"'}, epoch)


def _config(tmp_path: Path, **overrides: object) -> NodeConfig:
    values: dict[str, object] = {"node": "master", "cells": (), "delivery": "local", "backfill_days": 30, "max_bytes": 64 * 1024 * 1024, "max_seconds": 60.0}
    values.update(overrides)
    _ = tmp_path
    return NodeConfig(**values)  # type: ignore[arg-type]


def _write(path: Path, text: str, *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        handle.write(text)


def _rows(store: NodeStore) -> list[tuple[object, ...]]:
    return store.connection.execute(
        "select hour_epoch, project, agent, provider, model, route, input, cached_input, output, total, requests from hourly order by hour_epoch, model"
    ).fetchall()


def test_cumulative_deltas_skip_repeats_and_survive_counter_reset() -> None:
    state = FileState()
    first = {"total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 5, "total_tokens": 105}}
    assert usage_delta(state, first) == (100, 40, 5, 0, 105)
    assert usage_delta(state, first) is None
    second = {"total_token_usage": {"input_tokens": 160, "cached_input_tokens": 90, "output_tokens": 9, "total_tokens": 169}}
    assert usage_delta(state, second) == (60, 50, 4, 0, 64)
    reset = {"total_token_usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1, "total_tokens": 11}}
    assert usage_delta(state, reset) == (10, 0, 1, 0, 11)
    claude = {"last_token_usage": {"input_tokens": 7, "cached_input_tokens": 3, "output_tokens": 2, "total_tokens": 9}}
    assert usage_delta(FileState(), claude) == (7, 3, 2, 0, 9)


def test_reader_keeps_partial_lines_and_ignores_content_mentions(tmp_path: Path) -> None:
    rollout = tmp_path / "r.jsonl"
    complete = _meta(THREAD, BASE) + _turn("gpt-6-astra", BASE) + _noise(BASE) + _cumulative(BASE + 10, 100, 0, 10)
    _write(rollout, complete + '{"timestamp":"2026-10-05T00:00:20Z","type":"event_msg","payload":{"type":"tok')
    state = FileState()
    with rollout.open("rb") as handle:
        result = read_new_lines(handle, state, budget=1 << 20)
    assert state.offset == len(complete.encode())
    assert [(event.model, event.usage) for event in result.events] == [("gpt-6-astra", (100, 0, 10, 0, 110))]
    assert state.thread_id == THREAD


def test_reader_respects_byte_budget_on_line_boundaries(tmp_path: Path) -> None:
    rollout = tmp_path / "r.jsonl"
    lines = [_cumulative(BASE + index, 100 * (index + 1), 0, index + 1) for index in range(5)]
    _write(rollout, "".join(lines))
    state = FileState()
    with rollout.open("rb") as handle:
        first = read_new_lines(handle, state, budget=len(lines[0]) + 1)
        assert len(first.events) == 2
        second = read_new_lines(handle, state, budget=1 << 20)
    assert len(second.events) == 3
    assert state.offset == rollout.stat().st_size


def _home(tmp_path: Path, name: str, route: str) -> Home:
    return Home(str(tmp_path / name), route)


def _lanes() -> LaneIndex:
    index = LaneIndex()
    index.by_thread[THREAD] = Lane("dev-main-cell-one", "dft-lane", "dft", "Driestar DFT")
    index.by_worktree["/work/claude"] = Lane("dev-main-cell-one", "claude-lane", "potaito", None)
    return index


def test_collect_counts_each_request_exactly_once_across_runs(tmp_path: Path) -> None:
    codex = _home(tmp_path, "codex", "codex_account")
    claude = _home(tmp_path, "claude", "claude_code")
    codex_file = tmp_path / "codex/sessions/2026/10/05" / f"rollout-2026-10-05T00-00-00-{THREAD}.jsonl"
    claude_file = tmp_path / "claude/sessions/2026/10/05" / f"rollout-2026-10-05T00-00-00-{CLAUDE_THREAD}.jsonl"
    _write(codex_file, _meta(THREAD, BASE) + _turn("gpt-6-astra", BASE) + _cumulative(BASE + 60, 1000, 600, 50) + _cumulative(BASE + 61, 1000, 600, 50))
    _write(claude_file, _meta(CLAUDE_THREAD, BASE, cwd="/work/claude") + _turn("opus", BASE) + _last(BASE + HOUR + 5, 500, 400, 20))
    store = NodeStore(tmp_path / "state/ledger.sqlite3")
    config = _config(tmp_path)

    def run() -> None:
        collect(config, store, now=BASE + 2 * HOUR, home_finder=lambda _config: [codex, claude], lane_loader=lambda _config: (_lanes(), []))

    run()
    run()
    assert _rows(store) == [
        (BASE, "dft", "dft-lane", "openai", "gpt-6-astra", "codex_account", 1000, 600, 50, 1050, 1),
        (BASE + HOUR, "potaito", "claude-lane", "anthropic", "claude-opus", "claude_code", 500, 400, 20, 520, 1),
    ]
    _write(codex_file, _cumulative(BASE + HOUR + 10, 1500, 1000, 70), append=True)
    run()
    rows = _rows(store)
    assert (BASE + HOUR, "dft", "dft-lane", "openai", "gpt-6-astra", "codex_account", 500, 400, 20, 520, 1) in rows
    assert len(rows) == 3
    store.close()


def test_collect_skips_old_files_and_counts_only_inside_the_horizon(tmp_path: Path) -> None:
    home = _home(tmp_path, "codex", "codex_account")
    old = tmp_path / "codex/sessions/2026/08/01/rollout-old-00000000-0000-0000-0000-000000000000.jsonl"
    live = tmp_path / "codex/sessions/2026/09/01/rollout-live-11111111-1111-1111-1111-111111111111.jsonl"
    _write(old, _cumulative(BASE - 60 * 86_400, 10, 0, 1))
    os.utime(old, (BASE - 60 * 86_400, BASE - 60 * 86_400))
    _write(live, _cumulative(BASE - 40 * 86_400, 100, 0, 1) + _cumulative(BASE - 60, 150, 0, 2))
    store = NodeStore(tmp_path / "ledger.sqlite3")
    summary = collect(_config(tmp_path), store, now=BASE, home_finder=lambda _config: [home], lane_loader=lambda _config: (LaneIndex(), []))
    assert summary.files_read == 1
    assert _rows(store) == [(BASE - HOUR, "_nonlane", "-", "openai", "unknown", "codex_account", 50, 0, 1, 51, 1)]
    store.close()


def test_local_delivery_is_idempotent_and_pins_the_node(tmp_path: Path) -> None:
    home = _home(tmp_path, "codex", "codex_account")
    rollout = tmp_path / "codex/sessions/2026/10/05" / f"rollout-x-{THREAD}.jsonl"
    _write(rollout, _meta(THREAD, BASE) + _turn("gpt-5.6-sol", BASE) + _cumulative(BASE + 1, 10, 0, 1))
    store = NodeStore(tmp_path / "ledger.sqlite3")
    fleet = tmp_path / "fleet.sqlite3"
    config = _config(tmp_path)
    collect(config, store, now=BASE + 60, home_finder=lambda _config: [home], lane_loader=lambda _config: (_lanes(), []))
    assert deliver(config, store, version="test", fleet_db=fleet)["rows"] == 1
    assert deliver(config, store, version="test", fleet_db=fleet)["rows"] == 0
    connection = connect_fleet(fleet)
    replay = '{"kind":"header"}\n' + json.dumps(next(iter(NodeStore(tmp_path / "ledger.sqlite3").rows_since(0, 10)))) + "\n"
    ingest(connection, "jeff-dev", io.StringIO(replay))
    ingest(connection, "jeff-dev", io.StringIO(replay))
    nodes = connection.execute("select node, total from token_usage_hourly order by node").fetchall()
    assert nodes == [("jeff-dev", 11), ("master", 11)]
    with pytest.raises(ValueError, match="aligned"):
        ingest(connection, "jeff-dev", io.StringIO('{"hour_epoch": 5, "cell": "x"}\n'))
    with pytest.raises(ValueError, match="node"):
        ingest(connection, "../evil", io.StringIO(""))
    connection.close()
    store.close()


def _fleet_with(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    fleet = tmp_path / "fleet.sqlite3"
    connection = connect_fleet(fleet)
    header = json.dumps({"kind": "header", "collected_at": BASE, "backlog_bytes": 0})
    body = "\n".join([header, *(json.dumps({"change_seq": 1, "project_title": None, "reasoning": 0, "requests": 1, "cell": "c", "agent": "a", "route": "codex_account", **row}) for row in rows)])
    ingest(connection, "master", io.StringIO(body + "\n"))
    connection.close()
    return fleet


def test_report_layers_fold_into_top_series_and_other(tmp_path: Path) -> None:
    rows = [
        {"hour_epoch": BASE + HOUR * (index % 3), "project": f"p{index}", "provider": "openai" if index % 2 else "anthropic", "model": f"m{index}", "input": 100 * (index + 1), "cached_input": 10, "output": 5, "total": 100 * (index + 1) + 5}
        for index in range(9)
    ]
    report = build_report(_fleet_with(tmp_path, rows), "24h", expected_nodes=("master", "fsn1"), now=BASE + 3 * HOUR + 30)
    dimensions = report["dimensions"]
    assert isinstance(dimensions, dict)
    projects = dimensions["project"]["series"]
    assert [item["key"] for item in projects][:2] == ["p8", "p7"]
    assert projects[-1]["other"] is True
    assert projects[-1]["label"] == "Other (2)"
    providers = {item["key"]: item for item in dimensions["provider"]["series"]}
    assert providers["openai"]["color_slot"] == 0
    assert providers["anthropic"]["color_slot"] == 1
    assert len(report["buckets"]) == 24
    total = sum(sum(item["points"]["total"]) for item in projects)
    assert total == sum(int(str(row["total"])) for row in rows)
    coverage = report["coverage"]
    assert isinstance(coverage, dict)
    assert {item["name"]: item["stale"] for item in coverage["sources"]} == {"fsn1": True, "master": False}


def test_report_without_store_is_explicitly_unavailable(tmp_path: Path) -> None:
    report = build_report(tmp_path / "missing.sqlite3", "7d", expected_nodes=("master",), now=BASE)
    assert report["dimensions"] is None
    assert report["error"]
    with pytest.raises(ValueError, match="range"):
        build_report(tmp_path / "missing.sqlite3", "1y", expected_nodes=(), now=BASE)


def test_horizon_seek_counts_only_window_deltas_with_restored_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from .token_ledger import rollout as rollout_module  # noqa: PLC0415 - patch module constants

    monkeypatch.setattr(rollout_module, "_SEEK_MIN_BYTES", 1_000)
    monkeypatch.setattr(rollout_module, "_SEEK_PRECISION", 256)
    monkeypatch.setattr(rollout_module, "_PRIMER_BYTES", 3_000)
    lines = [_meta(THREAD, BASE - 10 * 86_400), _turn("gpt-5.6-terra", BASE - 10 * 86_400)]
    for index in range(400):
        lines.append(_cumulative(BASE - 10 * 86_400 + index * 2_000, 1_000 * (index + 1), 0, index + 1))
    horizon = BASE - 10 * 86_400 + 300 * 2_000 - 1
    rollout = tmp_path / "big.jsonl"
    _write(rollout, "".join(lines))
    state = FileState(count_from=horizon)
    with rollout.open("rb") as handle:
        rollout_module.prime_for_horizon(handle, rollout.stat().st_size, state)
        assert 0 < state.offset < rollout.stat().st_size // 2 * 2
        result = read_new_lines(handle, state, budget=1 << 30)
    assert state.thread_id == THREAD
    assert {event.model for event in result.events} == {"gpt-5.6-terra"}
    assert sum(event.usage[0] for event in result.events) == 100 * 1_000
    assert sum(event.usage[2] for event in result.events) == sum(range(301, 401)) - sum(range(300, 400))
