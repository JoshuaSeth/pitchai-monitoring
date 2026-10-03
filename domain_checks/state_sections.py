# Copyright (c) 2026 PitchAI. All rights reserved.
"""Schema-six defaults and health-section decoding for monitor restarts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .cycle_values import bool_field, coerce_float, coerce_int
from .state_values import coerce_bool_dict, coerce_float_dict, coerce_int_dict, coerce_str_list_dict

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .event_bus_delivery import JsonObject, JsonValue

_HEALTH_SECTIONS = ("host_health", "performance", "slo", "tls", "dns", "red", "container_health", "proxy", "meta")
_DOMAIN_SECTIONS = ("synthetic", "web_vitals", "api_contract")
_TIMED_SECTIONS = frozenset({"tls", "dns", "container_health"})


def decode_health_sections(raw: Mapping[str, JsonValue]) -> JsonObject:
    """Decode present sections, preserving distinct counters for every monitor.

    Returns:
        Only mapping-valued sections; absent or malformed sections use defaults.
    """
    result: JsonObject = {}
    for name in _HEALTH_SECTIONS:
        value = raw.get(name)
        if not isinstance(value, dict):
            continue
        section: JsonObject = {
            "last_ok": bool_field(value, "last_ok", default=True),
            "fail_streak": coerce_int(value.get("fail_streak")),
            "success_streak": coerce_int(value.get("success_streak")),
        }
        if name in _TIMED_SECTIONS:
            section["last_run_ts"] = coerce_float(value.get("last_run_ts"))
        if name == "host_health":
            section["cpu_prev_total"] = coerce_int(value.get("cpu_prev_total"))
            section["cpu_prev_idle"] = coerce_int(value.get("cpu_prev_idle"))
        elif name == "dns":
            address_map = coerce_str_list_dict(value.get("last_ips"))
            persisted_addresses: JsonObject = {}
            for domain, addresses in address_map.items():
                persisted_addresses[domain] = list(addresses)
            section["last_ips"] = persisted_addresses
        elif name == "container_health":
            section["restart_counts"] = dict(coerce_int_dict(value.get("restart_counts")))
        elif name == "meta":
            section["state_write_fail_streak"] = coerce_int(value.get("state_write_fail_streak"))
        result[name] = section
    for name in _DOMAIN_SECTIONS:
        value = raw.get(name)
        if isinstance(value, dict):
            result[name] = {
                "last_ok": dict(coerce_bool_dict(value.get("last_ok"))),
                "fail_streak": dict(coerce_int_dict(value.get("fail_streak"))),
                "success_streak": dict(coerce_int_dict(value.get("success_streak"))),
                "last_run_ts": dict(coerce_float_dict(value.get("last_run_ts"))),
            }
    return result


def default_monitor_state() -> JsonObject:
    """Allocate independent schema-six state for a missing or unreadable file.

    Returns:
        Fresh nested values, with legacy recovery and dashboard defaults intact.
    """
    sections: JsonObject = {}
    for name in (*_HEALTH_SECTIONS, *_DOMAIN_SECTIONS):
        sections[name] = {}
    state: JsonObject = {
        "version": 6,
        "history_ok_mode": "effective",
        "last_ok": {},
        "fail_streak": {},
        "success_streak": {},
        "history": {},
        "signal_history": {},
        "dispatch_history": [],
        "dispatch_last": {},
        "events": [],
        "event_bus_outbox": [],
        "host_last_snapshot": {},
        "browser_degraded_active": False,
        "browser_degraded_first_seen_ts": 0.0,
        "browser_launch_last_error": None,
        "browser_degraded_last_notice_ts": 0.0,
    }
    state.update(decode_health_sections(sections))
    return state
