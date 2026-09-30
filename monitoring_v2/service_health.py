# Copyright (c) 2026 PitchAI. All rights reserved.
"""Role-aware health command shared by the deployed monitoring containers."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from httpx import HTTPError

from .service_health_evidence import container_start_epoch, sanitize_fragment
from .service_health_model import STATUS_UNHEALTHY, HealthReport
from .service_health_request import parse_request
from .service_health_roles import UsageError, probe

if TYPE_CHECKING:
    from .service_health_request import HealthProbeRequest

_PROC_FILES: tuple[str, ...] = ("/proc/uptime", "/proc/1/stat")
_UNREADABLE_REASONS: dict[str, str] = {
    "registry": "registry_liveness_unreadable",
}
_MALFORMED_REASONS: dict[str, str] = {
    "registry": "registry_probe_invalid_response",
}


def unusable_evidence_report(*, request: HealthProbeRequest, failure: BaseException) -> HealthReport:
    """Classify one unusable-evidence failure into an operator report.

    A failed drain of retained evidence never asks for a restart: the worker
    process is alive and the report names the evidence that could not be read.

    Args:
        request: Resolved role, evidence path and thresholds.
        failure: Failure raised while collecting role evidence.

    Returns:
        An ``unhealthy`` report with a non-secret reason and classification.
    """
    return HealthReport(
        role=request.role,
        service=request.service,
        status=STATUS_UNHEALTHY,
        reason=_failure_reason(request.role, failure),
        detail=(
            f"state_path={request.evidence_path}",
            f"error_kind={sanitize_fragment(type(failure).__name__)}",
        ),
    )


def _failure_reason(role: str, failure: BaseException) -> str:
    if isinstance(failure, HTTPError):
        return "registry_unreachable"
    if isinstance(failure, sqlite3.Error):
        return "registry_database_unusable"
    if isinstance(failure, OSError):
        return _UNREADABLE_REASONS.get(role, "evidence_unreadable")
    return _MALFORMED_REASONS.get(role, "evidence_malformed")


def _usage_exit(message: str) -> int:
    """Return the exit code and report for one unusable invocation.

    Args:
        message: Narrow invocation or configuration failure token.

    Returns:
        The process exit code for an unusable invocation.
    """
    report = HealthReport(
        role="unknown",
        service="unknown",
        status=STATUS_UNHEALTHY,
        reason="usage_error",
        detail=(f"detail={sanitize_fragment(message)}",),
    )
    sys.stderr.write(f"{report.render()}\n")
    return 2


if __name__ == "__main__":
    proc_texts: dict[str, str] = {}
    for _proc_file in _PROC_FILES:
        try:
            proc_texts[_proc_file] = Path(_proc_file).read_text(encoding="utf-8")
        except OSError:
            proc_texts[_proc_file] = ""
    selected_now = time.time()
    try:
        selected_request = parse_request(sys.argv[1:])
    except UsageError as usage_failure:
        raise SystemExit(_usage_exit(str(usage_failure))) from usage_failure
    except (TypeError, ValueError) as config_failure:
        raise SystemExit(_usage_exit(str(config_failure))) from config_failure
    try:
        selected_report = probe(
            selected_request,
            now=selected_now,
            start_epoch=container_start_epoch(
                now=selected_now,
                uptime_text=proc_texts["/proc/uptime"],
                pid_one_stat_text=proc_texts["/proc/1/stat"],
            ),
        )
    except (HTTPError, OSError, TypeError, ValueError, sqlite3.Error) as evidence_failure:
        selected_report = unusable_evidence_report(
            request=selected_request,
            failure=evidence_failure,
        )
    sys.stdout.write(f"{selected_report.render()}\n")
    raise SystemExit(selected_report.exit_code)
