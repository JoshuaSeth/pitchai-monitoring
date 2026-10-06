# Copyright (c) 2026 PitchAI. All rights reserved.
"""Exporter defaults per short OS hostname of the three Agent Engine servers.

Each server answers to its old and its new (``pitchai-agent-engine-*``) hostname.
Both names resolve to the same defaults: node labels and cell slugs never change.
An explicit ``/etc/pitchai-token-ledger/config.json`` overrides these defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .json_types import JsonObject

_CONTROL_PLANE = "/code/pitchai-cli-new/.pitchai-state/control-plane.sqlite3"
_MASTER: JsonObject = {
    "node": "master",
    "cells": [
        ["dev-main-cell-one", _CONTROL_PLANE],
        ["dev-monitoring-cell", "/code/pitchai-cli-new-monitoring/.pitchai-state/control-plane.sqlite3"],
    ],
    "extra_homes": [["/root/.codex", "voice"]],
    "delivery": "local",
}
_JEFF: JsonObject = {"node": "jeff-dev", "cells": [["dev-jeff-cell-two", _CONTROL_PLANE]]}
_FSN1: JsonObject = {"node": "fsn1", "cells": [["pitchai-fsn1-01", _CONTROL_PLANE]]}
HOST_DEFAULTS: dict[str, JsonObject] = {
    "pitchai-dev": _MASTER,
    "pitchai-agent-engine-master": _MASTER,
    "pitchai-jeff-dev": _JEFF,
    "pitchai-agent-engine-node-1": _JEFF,
    "pitchai-fsn1-01": _FSN1,
    "pitchai-agent-engine-node-2": _FSN1,
}
