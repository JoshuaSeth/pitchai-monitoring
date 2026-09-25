# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable public facade for monitoring dashboard aggregation."""

from e2e_registry.monitor_domains import summarize_domains
from e2e_registry.monitor_groups import summarize_domain_groups
from e2e_registry.monitor_inventory import load_monitor_data, load_yaml_config, normalize_domain_entries
from e2e_registry.monitor_series import domain_timeseries, signal_timeseries
from e2e_registry.monitor_signals import summarize_signals
from e2e_registry.monitor_summary import build_dashboard_summary
from e2e_registry.monitor_types import MonitorData
from e2e_registry.monitor_values import resolve_range

__all__ = [
    "MonitorData",
    "build_dashboard_summary",
    "domain_timeseries",
    "load_monitor_data",
    "load_yaml_config",
    "normalize_domain_entries",
    "resolve_range",
    "signal_timeseries",
    "summarize_domain_groups",
    "summarize_domains",
    "summarize_signals",
]
