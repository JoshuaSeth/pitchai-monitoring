# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed normalization of persisted monitor-state sections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain_checks.monitor_value_collections import (
    bool_dict,
    float_dict,
    int_dict,
    string_list_dict,
)
from domain_checks.monitor_values import bool_value, float_value, int_value, json_object

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue

_DEBOUNCE_SECTIONS = ("performance", "slo", "red", "proxy")
_PER_DOMAIN_SECTIONS = ("synthetic", "web_vitals", "api_contract")


def _debounce_section(raw: JsonValue) -> JsonObject:
    section = json_object(raw)
    return {
        "last_ok": bool_value(section.get("last_ok"), default=True),
        "fail_streak": int_value(section.get("fail_streak")),
        "success_streak": int_value(section.get("success_streak")),
    }


def _timed_section(raw: JsonValue) -> JsonObject:
    return {
        **_debounce_section(raw),
        "last_run_ts": float_value(json_object(raw).get("last_run_ts")),
    }


def _per_domain_section(raw: JsonValue) -> JsonObject:
    section = json_object(raw)
    return {
        "last_ok": bool_dict(section.get("last_ok")),
        "fail_streak": int_dict(section.get("fail_streak")),
        "success_streak": int_dict(section.get("success_streak")),
        "last_run_ts": float_dict(section.get("last_run_ts")),
    }


def normalize_sections(raw: JsonObject, state: JsonObject) -> None:
    """Normalize all structured signal sections into ``state`` in place."""
    for key in _DEBOUNCE_SECTIONS:
        if json_object(raw.get(key)):
            state[key] = _debounce_section(raw.get(key))
    for key in _PER_DOMAIN_SECTIONS:
        if json_object(raw.get(key)):
            state[key] = _per_domain_section(raw.get(key))
    if json_object(raw.get("tls")):
        state["tls"] = _timed_section(raw.get("tls"))
    dns = json_object(raw.get("dns"))
    if dns:
        state["dns"] = {**_timed_section(dns), "last_ips": string_list_dict(dns.get("last_ips"))}
    host = json_object(raw.get("host_health"))
    if host:
        state["host_health"] = {
            **_debounce_section(host),
            "cpu_prev_total": int_value(host.get("cpu_prev_total")),
            "cpu_prev_idle": int_value(host.get("cpu_prev_idle")),
        }
    container = json_object(raw.get("container_health"))
    if container:
        state["container_health"] = {
            **_timed_section(container),
            "restart_counts": int_dict(container.get("restart_counts")),
        }
    meta = json_object(raw.get("meta"))
    if meta:
        state["meta"] = {
            **_debounce_section(meta),
            "state_write_fail_streak": int_value(meta.get("state_write_fail_streak")),
        }
