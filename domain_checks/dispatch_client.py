# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable public facade for the domain-monitor Dispatcher client."""

from domain_checks.dispatch_gateway import (
    dispatch_job,
    get_run_record,
    get_run_status,
    wait_for_terminal_status,
)
from domain_checks.dispatch_logs import (
    get_last_agent_message,
    get_last_error_message,
    get_run_log_tail,
)
from domain_checks.dispatch_models import (
    DispatchConfig,
    DispatchRunStatus,
    extract_last_agent_message_from_exec_log,
    extract_last_error_message_from_exec_log,
    parse_dispatch_response,
    run_ui_url,
)

__all__ = [
    "DispatchConfig",
    "DispatchRunStatus",
    "dispatch_job",
    "extract_last_agent_message_from_exec_log",
    "extract_last_error_message_from_exec_log",
    "get_last_agent_message",
    "get_last_error_message",
    "get_run_log_tail",
    "get_run_record",
    "get_run_status",
    "parse_dispatch_response",
    "run_ui_url",
    "wait_for_terminal_status",
]
