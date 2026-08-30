# Copyright (c) 2026 PitchAI. All rights reserved.
"""Define the inventory-backed scope for global production signals."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_CANONICAL_CONFIG_PATH = Path(__file__).with_name("config.yaml")
_PRODUCTION_ENVIRONMENT = "production"
_DASHBOARD_ONLY_LINE = "      telegram: dashboard-only"
_DOMAINS_MARKER = "\ndomains:\n"
_RETIRED_MARKER = "\nretired_domains:\n"
_DOMAIN_ENTRY_MARKER = "\n  - domain: "


class ProductionScopeConfigurationError(ValueError):
    """The canonical domain inventory cannot define a safe signal scope."""


def _domain_entries() -> tuple[str, ...]:
    config = _CANONICAL_CONFIG_PATH.read_text(encoding="utf-8")
    if _DOMAINS_MARKER not in config or _RETIRED_MARKER not in config:
        message = "canonical monitoring config is missing active-domain boundaries"
        raise ProductionScopeConfigurationError(message)
    domains_block = config.split(_DOMAINS_MARKER, 1)[1].split(_RETIRED_MARKER, 1)[0]
    entries = tuple(("\n" + domains_block).split(_DOMAIN_ENTRY_MARKER)[1:])
    if not entries:
        message = "canonical monitoring config contains no active domains"
        raise ProductionScopeConfigurationError(message)
    return entries


def _excluded_domain(entry: str, *, index: int) -> str | None:
    lines = entry.splitlines()
    domain = lines[0].strip() if lines else ""
    environment_candidates = (line for line in lines if line.startswith("    environment: "))
    environment_lines = [line.strip() for line in environment_candidates]
    if not domain or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for character in domain):
        message = f"domains[{index}].domain is not a canonical hostname"
        raise ProductionScopeConfigurationError(message)
    if len(environment_lines) != 1:
        message = f"domains[{index}] must declare exactly one environment"
        raise ProductionScopeConfigurationError(message)
    environment = environment_lines[0].split(":", 1)[1].strip()
    dashboard_only = _DASHBOARD_ONLY_LINE in lines
    if environment != _PRODUCTION_ENVIRONMENT or dashboard_only:
        return domain.rstrip(".")
    return None


@cache
def production_signal_excluded_domains() -> frozenset[str]:
    """Return known hosts excluded from global production signals.

    Returns:
        Canonical non-production and dashboard-only hostnames.
    """
    exclusions: set[str] = set()
    for index, raw_entry in enumerate(_domain_entries()):
        domain = _excluded_domain(raw_entry, index=index)
        if domain is not None:
            exclusions.add(domain)
    return frozenset(exclusions)


def production_signal_includes(server: str | None) -> bool:
    """Return whether a server belongs in a global production signal.

    Unknown or missing server names remain included so new routes fail loud.

    Returns:
        ``False`` only for known non-production or dashboard-only hosts.
    """
    if server is None:
        return True
    normalized = server.strip().lower().rstrip(".")
    return not normalized or normalized not in production_signal_excluded_domains()
