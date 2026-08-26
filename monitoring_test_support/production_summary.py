# Copyright (c) 2026 PitchAI. All rights reserved.
"""Build a deterministic production-inventory summary for browser proof."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from domain_checks.json_types import text_value
from e2e_registry.monitor_dashboard import MonitorData
from e2e_registry.monitoring_v2.summary import build_dashboard_summary
from monitoring_test_support.dashboard_tabs import build_actionable_dashboard_summary
from monitoring_test_support.inventory import CONFIG_PATH, production_config, production_domains

if TYPE_CHECKING:
    from domain_checks.json_types import JsonObject

_FAILED_DOMAIN = "pitchai.net"
_FAILED_HTTP_STATUS = 503
_HEALTHY_HTTP_STATUS = 200


def production_dashboard_summary() -> JsonObject:
    """Return all production domains plus deterministic domain and DB failures."""
    now = time.time()
    last_ok: JsonObject = {}
    fail_streak: JsonObject = {}
    success_streak: JsonObject = {}
    history: JsonObject = {}
    for entry in production_domains():
        domain = text_value(entry.get("domain"))
        healthy = domain != _FAILED_DOMAIN
        last_ok[domain] = healthy
        fail_streak[domain] = 0 if healthy else 3
        success_streak[domain] = 3 if healthy else 0
        status_code = _HEALTHY_HTTP_STATUS if healthy else _FAILED_HTTP_STATUS
        history[domain] = [
            [now - 60, healthy, 100.0, 250.0, status_code],
            [now, healthy, 90.0, 230.0, status_code],
        ]
    state: JsonObject = {
        "updated_at": now,
        "last_ok": last_ok,
        "fail_streak": fail_streak,
        "success_streak": success_streak,
        "history": history,
        "events": [],
    }
    data = MonitorData(
        state=state,
        config=production_config(),
        state_path="/monitor/state.json",
        config_path=str(CONFIG_PATH),
        loaded_at_ts=now,
        state_error=None,
    )
    summary = build_dashboard_summary(
        data=data,
        now_ts=now,
        e2e_status_summary=None,
        e2e_dispatch_runs=[],
    )
    return build_actionable_dashboard_summary(summary, domain=_FAILED_DOMAIN)
