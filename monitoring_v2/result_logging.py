# Copyright (c) 2026 PitchAI. All rights reserved.
"""Inventory-aware severity for domain-result diagnostics; no record is dropped."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .json_types import json_object, object_list, optional_object
from .serialization_runtime import load_yaml

if TYPE_CHECKING:
    from pathlib import Path

_RESULT_DOMAIN = re.compile(r"^Domain (?:result|failing \(alert suppressed\)) domain=([a-z0-9.-]+)(?: |$)")


@dataclass(frozen=True)
class DomainResultLogFilter:
    """Keep quiet result records at INFO while preserving every other warning."""

    quiet_domains: frozenset[str]

    def __call__(self, record: logging.LogRecord) -> bool:
        """Adjust only known result warnings and retain every log record.

        Returns:
            True, including for unrelated warnings and errors.
        """
        match = _RESULT_DOMAIN.match(record.getMessage())
        if record.levelno == logging.WARNING and match and match[1] in self.quiet_domains:
            record.levelno = logging.INFO
            record.levelname = logging.getLevelName(logging.INFO)
        return True


def install_result_log_policy(config_path: Path) -> DomainResultLogFilter:
    """Load the selected inventory and install its diagnostic severity policy.

    Returns:
        The installed filter for caller-owned cleanup or inspection.
    """
    config = json_object(load_yaml(config_path.read_text(encoding="utf-8")))
    quiet: set[str] = set()
    for entry in object_list(config.get("domains")):
        policy = optional_object(entry.get("alert_policy"))
        domain = entry.get("domain")
        if policy.get("telegram") == "dashboard-only" and isinstance(domain, str):
            quiet.add(domain)
    result_filter = DomainResultLogFilter(frozenset(quiet))
    logging.getLogger("service-monitoring").addFilter(result_filter)
    return result_filter
