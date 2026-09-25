# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitoring state/configuration IO and inventory normalization."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import yaml

from domain_checks.history import coerce_history
from domain_checks.inventory import parse_domain_alert_policy
from e2e_registry.monitor_types import MonitorData
from e2e_registry.monitor_values import safe_int, safe_timestamp

if TYPE_CHECKING:
    from domain_checks.types import JsonObject, JsonValue
    from e2e_registry.monitor_types import MonitorRecord, MonitorRecords, MonitorValue


def _yaml_document(path: Path) -> tuple[MonitorRecord, str | None]:
    try:
        decoded = cast("MonitorValue", yaml.safe_load(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {}, f"missing_config: {path}"
    except (OSError, yaml.YAMLError) as exc:
        return {}, f"invalid_config: {path}: {type(exc).__name__}"
    if decoded is None:
        return {}, f"empty_config: {path}"
    if not isinstance(decoded, dict):
        return {}, f"invalid_config_root: {path}"
    return cast("MonitorRecord", decoded), None


def _json_document(path: Path) -> tuple[MonitorRecord, str | None]:
    try:
        decoded = cast("MonitorValue", json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {}, f"missing_state: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"invalid_state: {path}: {type(exc).__name__}"
    if not isinstance(decoded, dict):
        return {}, f"invalid_state_root: {path}"
    return cast("MonitorRecord", decoded), None


def load_yaml_config(path: Path) -> MonitorRecord:
    """Return monitor YAML data, or an empty object at the configuration IO edge."""
    document, _error = _yaml_document(path)
    return document


def _disabled_until_timestamp(value: MonitorValue) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    timestamp = safe_timestamp(value)
    if timestamp is not None:
        return timestamp
    if not isinstance(value, str):
        return None
    parsed_date = date.fromisoformat(value.strip())
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC).timestamp()


def _domain_record(entry: str | MonitorRecord, *, index: int) -> MonitorRecord | None:
    if isinstance(entry, str):
        domain = entry.strip()
        if not domain:
            return None
        return cast(
            "MonitorRecord",
            {
                "domain": domain,
                "label": domain,
                "group": "ungrouped",
                "environment": "unspecified",
                "kind": "application",
                "disabled": False,
                "disabled_reason": None,
                "disabled_until_ts": None,
                "alert_policy": parse_domain_alert_policy(None).to_dashboard_dict(),
            },
        )
    domain = str(entry.get("domain") or "").strip()
    if not domain:
        return None
    alert_policy = parse_domain_alert_policy(cast("JsonObject", entry), path=f"domains[{index}]")
    return cast(
        "MonitorRecord",
        {
            "domain": domain,
            "label": str(entry.get("label") or domain).strip(),
            "group": str(entry.get("group") or "ungrouped").strip(),
            "environment": str(entry.get("environment") or "unspecified").strip(),
            "kind": str(entry.get("kind") or "application").strip(),
            "disabled": bool(entry.get("disabled")) or entry.get("enabled") is False,
            "disabled_reason": str(entry.get("disabled_reason") or "").strip() or None,
            "disabled_until_ts": _disabled_until_timestamp(entry.get("disabled_until")),
            "alert_policy": alert_policy.to_dashboard_dict(),
        },
    )


def normalize_domain_entries(domains_config: MonitorValue) -> MonitorRecords:
    """Return normalized, de-duplicated monitoring inventory entries."""
    if not isinstance(domains_config, list):
        return []
    normalized: MonitorRecords = []
    for index, entry in enumerate(domains_config):
        if not isinstance(entry, str | dict):
            continue
        record = _domain_record(entry, index=index)
        if record is not None:
            normalized.append(record)
    seen: set[str] = set()
    deduplicated: MonitorRecords = []
    for record in normalized:
        domain = str(record.get("domain") or "").strip()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        deduplicated.append(record)
    return deduplicated


def normalize_domain_groups(groups_config: MonitorValue) -> MonitorRecords:
    """Return validated domain-group display definitions in configured order."""
    if not isinstance(groups_config, dict):
        return []
    groups: MonitorRecords = []
    for group_id, raw in groups_config.items():
        cleaned_id = str(group_id or "").strip()
        if not cleaned_id or not isinstance(raw, dict):
            continue
        groups.append(
            {
                "id": cleaned_id,
                "label": str(raw.get("label") or cleaned_id.replace("-", " ").title()).strip(),
                "description": str(raw.get("description") or "").strip() or None,
                "order": safe_int(raw.get("order")) or 1000,
            },
        )
    return sorted(
        groups,
        key=lambda group: (safe_int(group["order"]) or 1000, str(group["label"]).lower()),
    )


def load_monitor_data(*, state_path: str, config_path: str) -> MonitorData:
    """Load normalized monitoring state and surface every IO validation error.

    Returns:
        The normalized state, inventory, provenance, and aggregate IO error.
    """
    normalized_state_path = str(state_path or "").strip()
    normalized_config_path = str(config_path or "").strip()
    if normalized_state_path:
        state, state_error = _json_document(Path(normalized_state_path))
    else:
        state, state_error = {}, "missing_state_path"
    if normalized_config_path:
        config, config_error = _yaml_document(Path(normalized_config_path))
    else:
        config, config_error = {}, "missing_config_path"
    raw_history = cast("JsonValue", state.get("history"))
    state["history"] = cast("MonitorValue", coerce_history(raw_history))
    possible_errors = (state_error, config_error)
    errors = list(filter(None, possible_errors))
    return MonitorData(
        state=state,
        config=config,
        state_path=normalized_state_path,
        config_path=normalized_config_path,
        loaded_at_ts=time.time(),
        state_error="; ".join(errors) or None,
    )
