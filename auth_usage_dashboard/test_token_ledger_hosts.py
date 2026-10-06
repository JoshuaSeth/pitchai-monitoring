# Copyright (c) 2026 PitchAI. All rights reserved.
"""Proof that the 2026-10 server rename keeps every ledger identity stable."""

from __future__ import annotations

import os
from contextlib import closing
from typing import TYPE_CHECKING
from unittest.mock import patch

from ._timeseries_test_fixtures import check_equal, require_array
from .timeseries_types import require_object
from .token_ledger.coverage import node_coverage
from .token_ledger.fleet_store import connect_fleet
from .token_ledger.sources import load_config

if TYPE_CHECKING:
    from pathlib import Path

    from .token_ledger.sources import NodeConfig

RENAMED_HOSTS = (
    ("pitchai-dev", "pitchai-agent-engine-master", "master"),
    ("pitchai-jeff-dev", "pitchai-agent-engine-node-1", "jeff-dev"),
    ("pitchai-fsn1-01", "pitchai-agent-engine-node-2", "fsn1"),
)


def _config_on(hostname: str, config_file: Path) -> NodeConfig:
    fake = os.uname_result(("Linux", hostname, "6.8.0", "#1 SMP", "x86_64"))
    with patch.object(os, "uname", new=lambda: fake):
        return load_config(config_file)


def test_new_hostnames_resolve_to_the_same_node_config(tmp_path: Path) -> None:
    """Prove each new hostname yields exactly the node, cells and homes of its old hostname."""
    missing = tmp_path / "absent-config.json"
    for old, new, node in RENAMED_HOSTS:
        before = _config_on(old, missing)
        check_equal(before.node, node, f"{old} keeps its node label")
        check_equal(_config_on(new, missing), before, f"{new} resolves like {old}")
        check_equal(_config_on(f"{new}.example", missing), before, f"a fully qualified {new} resolves like {old}")
    master = _config_on("pitchai-agent-engine-master", missing)
    check_equal(master.delivery, "local", "master still delivers into its local fleet store")
    check_equal(master.extra_homes, (("/root/.codex", "voice"),), "master still reads the voice home")
    node_two = _config_on("pitchai-agent-engine-node-2", missing)
    check_equal([cell for cell, _ in node_two.cells], ["pitchai-fsn1-01"], "the fsn1 cell slug is unchanged")


def test_explicit_config_file_wins_over_any_hostname(tmp_path: Path) -> None:
    """Prove a node config file names the node even when the hostname is unknown."""
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"node": "jeff-dev", "cells": [["dev-jeff-cell-two", "/cp.sqlite3"]], "delivery": "ssh"}',
        encoding="utf-8",
    )
    config = _config_on("unrelated-host", config_file)
    check_equal(config.node, "jeff-dev", "the file names the node")
    check_equal(config.cells, (("dev-jeff-cell-two", "/cp.sqlite3"),), "the file lists the cells")


def test_coverage_shows_new_names_but_keeps_node_keys(tmp_path: Path) -> None:
    """Prove coverage labels use the new server names while ``name`` stays the stored node key."""
    with closing(connect_fleet(tmp_path / "fleet.sqlite3")) as connection:
        coverage = node_coverage(connection, ("master", "jeff-dev", "fsn1", "spare"), 0.0)
    labels: dict[str, str] = {}
    for item in require_array(coverage["sources"], "sources"):
        source = require_object(item, description="source")
        labels[str(source["name"])] = str(source["label"])
    expected: dict[str, str] = {
        "fsn1": "pitchai-agent-engine-node-2",
        "jeff-dev": "pitchai-agent-engine-node-1",
        "master": "pitchai-agent-engine-master",
        "spare": "spare",
    }
    check_equal(labels, expected, "display labels map old node keys to the new server names")
