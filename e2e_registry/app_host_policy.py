# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing registry destination admission and startup quarantine policy."""

from __future__ import annotations

import ipaddress
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import db as dbm
from .dashboard_data import load_yaml
from .dashboard_inventory import normalize_domain_entries
from .stepflow import validate_base_url

if TYPE_CHECKING:
    from domain_checks.config_values import ConfigValue

    from .app_context import RegistryContext
    from .settings import RegistrySettings

# Numeric reserved hosts are classified by ipaddress below; names retain the
# exact explicit/suffix checks without confusing admission data with bindings.
_RESERVED_HOSTS: Final = {"example.com", "example.org", "example.net", "localhost"}
_RESERVED_SUFFIXES: Final = (
    ".example.com", ".example.org", ".example.net", ".localhost", ".local", ".internal", ".invalid", ".test",
)


def url_host(base_url: str) -> str:
    """Keep malformed URL extraction separate from destination admission.

    Returns:
        The normalized hostname or the existing empty parse-failure sentinel.
    """
    host = ""
    # The original helper treats all ordinary parser errors as an empty host.
    with suppress(Exception):
        host = (urlsplit(str(base_url or "").strip()).hostname or "").strip().lower()
    return host.rstrip(".")


def host_is_reserved_or_non_public(host: str) -> bool:
    """Classify reserved names and numeric addresses without resolving DNS.

    Returns:
        Whether strict policy rejects the normalized host.
    """
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized or normalized in _RESERVED_HOSTS:
        return True
    if any(normalized.endswith(suffix) for suffix in _RESERVED_SUFFIXES):
        return True
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    with suppress(ValueError):
        address = ipaddress.ip_address(normalized)
    if address is not None:
        return (
            address.is_loopback or address.is_private or address.is_link_local
            or address.is_multicast or address.is_reserved or address.is_unspecified
        )
    return "." not in normalized


def load_monitored_allowlist_hosts(settings: RegistrySettings) -> set[str]:
    """Load allowed monitored hosts only when the existing option enables it.

    Returns:
        Normalized configured inventory names, without host or browser probes.
    """
    if not settings.base_url_allow_monitored_domains:
        return set()
    config = load_yaml(Path(str(settings.monitor_config_path or "").strip()))
    entries = normalize_domain_entries(config.get("domains"))
    hosts: set[str] = set()
    for entry in entries:
        domain = str((entry or {}).get("domain") or "").strip().lower().rstrip(".")
        if domain:
            hosts.add(domain)
    return hosts


@dataclass(frozen=True)
class RegistryHostPolicy:
    """Apply current settings at the same validation and quarantine boundaries."""

    context: RegistryContext

    def allowed_hosts(self) -> set[str]:
        """Prefer the explicit nonempty allowlist before consulting inventory.

        Returns:
            The current normalized allowlist.
        """
        settings = self.context.settings
        allowed: set[str] = set()
        for host in settings.base_url_allowed_hosts:
            if str(host).strip():
                allowed.add(host.strip().lower().rstrip("."))
        return allowed or load_monitored_allowlist_hosts(settings)

    def is_disallowed_host(self, host: str) -> bool:
        """Apply strict policy without normalizing away the caller's identity.

        Returns:
            Whether the existing test must be quarantined.
        """
        settings = self.context.settings
        if not settings.strict_base_url_policy:
            return False
        if host_is_reserved_or_non_public(host):
            return True
        allowed = self.allowed_hosts()
        return bool(allowed and host not in allowed)

    def validate_base_url(self, raw_base_url: str) -> str:
        """Validate URL syntax before strict destination admission.

        Returns:
            The validated URL with the original spelling.

        Raises:
            HTTPException: Strict policy rejects a reserved or unlisted host.
        """
        base = validate_base_url(raw_base_url)
        settings = self.context.settings
        if not settings.strict_base_url_policy:
            return base
        host = url_host(base)
        if host_is_reserved_or_non_public(host):
            raise HTTPException(status_code=400, detail="base_url_not_allowed_host")
        allowed = self.allowed_hosts()
        if allowed and host not in allowed:
            raise HTTPException(status_code=400, detail="base_url_not_monitored_domain")
        return base

    def quarantine_disallowed_tests(self) -> int:
        """Retain startup's sequential disabled-state writes after schema setup.

        Returns:
            The count of database writes that reported success.
        """
        settings = self.context.settings
        if not settings.strict_base_url_policy:
            return 0
        summary = cast("ConfigValue", dbm.status_summary(settings))
        tests = summary.get("tests") if isinstance(summary, dict) else None
        if not isinstance(tests, list):
            return 0
        changed = 0
        for item in tests:
            if not isinstance(item, dict):
                continue
            host = url_host(str(item.get("base_url") or ""))
            if not self.is_disallowed_host(host):
                continue
            tenant_id = str(item.get("tenant_id") or "").strip()
            test_id = str(item.get("test_id") or "").strip()
            if not tenant_id or not test_id:
                continue
            changed += bool(dbm.set_test_disabled(
                settings, tenant_id=tenant_id, test_id=test_id, disabled=True,
                reason=f"auto-disabled disallowed base_url host: {host or 'unknown'}", until_ts=None,
            ))
        return changed
