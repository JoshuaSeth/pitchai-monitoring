# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable public facade for common domain-check support."""

from __future__ import annotations

from domain_checks.common_browser import browser_check
from domain_checks.common_browser_runtime import (
    chromium_launch_arguments,
    find_chromium_executable,
    is_browser_infrastructure_error,
)
from domain_checks.common_config import load_domain_spec_from_module_dict
from domain_checks.common_http import http_get_check
from domain_checks.common_models import (
    DEFAULT_MAINTENANCE_TEXT,
    DomainCheckResult,
    DomainCheckSpec,
    SelectorCheck,
    SelectorState,
)
from domain_checks.common_text import html_to_visible_text, normalize_text, safe_url

_html_to_visible_text = html_to_visible_text
_is_browser_infra_error = is_browser_infrastructure_error
_normalize_text = normalize_text
_safe_url = safe_url

__all__ = [
    "DEFAULT_MAINTENANCE_TEXT",
    "DomainCheckResult",
    "DomainCheckSpec",
    "SelectorCheck",
    "SelectorState",
    "_html_to_visible_text",
    "_is_browser_infra_error",
    "_normalize_text",
    "_safe_url",
    "browser_check",
    "chromium_launch_arguments",
    "find_chromium_executable",
    "http_get_check",
    "is_browser_infrastructure_error",
    "load_domain_spec_from_module_dict",
]
