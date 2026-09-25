# Copyright (c) 2026 PitchAI. All rights reserved.
"""Input normalization and target policy for registry web routes."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import HTTPException

from e2e_registry import db as dbm
from e2e_registry import monitor_dashboard as md
from e2e_registry.stepflow import validate_base_url

if TYPE_CHECKING:
    from e2e_registry.models import JsonValue
    from e2e_registry.settings import RegistrySettings

_ALLOWED_TEST_KINDS = {"stepflow", "playwright_python", "puppeteer_js"}
_RESERVED_BASE_URL_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "127.0.0.1",
    "::1",
}
_RESERVED_BASE_URL_SUFFIXES = (
    ".example.com",
    ".example.org",
    ".example.net",
    ".localhost",
    ".local",
    ".internal",
    ".invalid",
    ".test",
)
_NUMBER_PATTERN = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_IPV4_OCTET_COUNT = 4
_IPV4_OCTET_MAXIMUM = 255


def normalize_test_kind(kind: str) -> str:
    """Return the canonical supported test kind, or an empty string."""
    aliases = {
        "stepflow": "stepflow",
        "yaml": "stepflow",
        "yml": "stepflow",
        "playwright-python": "playwright_python",
        "playwright_python": "playwright_python",
        "pw_python": "playwright_python",
        "puppeteer-js": "puppeteer_js",
        "puppeteer_js": "puppeteer_js",
        "pptr": "puppeteer_js",
    }
    normalized = str(kind or "").strip().lower()
    canonical = aliases.get(normalized, normalized)
    return canonical if canonical in _ALLOWED_TEST_KINDS else ""


def form_checkbox_enabled(value: str) -> bool:
    """Return whether an HTML checkbox submitted an affirmative value."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def safe_filename(name: str, *, default: str) -> str:
    """Return a bounded filename without directory or unsupported characters."""
    base = Path(str(name or "")).name
    cleaned = "".join(character for character in base if character.isalnum() or character in "-_.+")
    normalized = cleaned[:120].strip(".")
    return normalized or default


def parse_until(value: JsonValue) -> float | None:
    """Parse a positive Unix timestamp, ISO datetime, or ISO date.

    Returns:
        A positive Unix timestamp, or ``None`` for an empty/non-positive value.

    Raises:
        TypeError: If the value has an unsupported JSON type.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        message = "invalid_until: booleans are not timestamps"
        raise TypeError(message)
    if isinstance(value, int | float):
        timestamp = float(value)
        return timestamp if timestamp > 0 else None
    if not isinstance(value, str):
        message = "invalid_until: expected text or number"
        raise TypeError(message)
    raw = value.strip()
    if not raw:
        return None
    if _NUMBER_PATTERN.fullmatch(raw):
        timestamp = float(raw)
        return timestamp if timestamp > 0 else None
    if "T" in raw or " " in raw:
        iso_value = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(iso_value)
        aware = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        return aware.timestamp()
    parsed_date = date.fromisoformat(raw)
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=UTC).timestamp()


def url_host(base_url: str) -> str:
    """Extract a normalized hostname from a validated URL.

    Returns:
        The lowercase hostname without a trailing dot.
    """
    parsed = urlsplit(str(base_url or "").strip())
    return (parsed.hostname or "").strip().lower().rstrip(".")


def host_is_reserved_or_non_public(host: str) -> bool:
    """Identify reserved, local, private, and bare internal hostnames.

    Returns:
        Whether strict target policy must reject the host.
    """
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized or normalized in _RESERVED_BASE_URL_HOSTS:
        return True
    if any(normalized.endswith(suffix) for suffix in _RESERVED_BASE_URL_SUFFIXES):
        return True
    numeric_host = all(character.isdigit() or character == "." for character in normalized)
    if numeric_host:
        octets = normalized.split(".")
        valid_ipv4 = len(octets) == _IPV4_OCTET_COUNT and all(
            octet and int(octet) <= _IPV4_OCTET_MAXIMUM for octet in octets
        )
        if not valid_ipv4:
            return True
    looks_like_ip = ":" in normalized or numeric_host
    if looks_like_ip:
        address = ipaddress.ip_address(normalized)
        return bool(
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified,
        )
    return "." not in normalized


def load_monitored_allowlist_hosts(settings: RegistrySettings) -> set[str]:
    """Load configured monitoring inventory hosts for strict target policy.

    Returns:
        The normalized monitored domain names.
    """
    if not settings.base_url_allow_monitored_domains:
        return set()
    config = md.load_yaml_config(Path(str(settings.monitor_config_path or "").strip()))
    entries = md.normalize_domain_entries(config.get("domains"))
    hosts: set[str] = set()
    for entry in entries:
        domain = str(entry.get("domain") or "").strip().lower().rstrip(".")
        if domain:
            hosts.add(domain)
    return hosts


@dataclass(frozen=True)
class BaseUrlPolicy:
    """Strict allowlist policy bound to one registry configuration."""

    settings: RegistrySettings

    def allowed_hosts(self) -> set[str]:
        """Return the explicitly configured or monitored host allowlist."""
        configured_hosts = self.settings.base_url_allowed_hosts
        nonempty_hosts = filter(lambda host: str(host).strip(), configured_hosts)
        explicit_hosts = {str(host).strip().lower().rstrip(".") for host in nonempty_hosts}
        return explicit_hosts or load_monitored_allowlist_hosts(self.settings)

    def is_disallowed_host(self, host: str) -> bool:
        """Return whether strict target policy rejects a host."""
        if not self.settings.strict_base_url_policy:
            return False
        if host_is_reserved_or_non_public(host):
            return True
        allowed = self.allowed_hosts()
        return bool(allowed and host not in allowed)

    def validate(self, raw_base_url: str) -> str:
        """Return a validated URL or reject a disallowed target.

        Raises:
            HTTPException: If strict target policy rejects the URL host.
        """
        base_url = validate_base_url(raw_base_url)
        if not self.settings.strict_base_url_policy:
            return base_url
        host = url_host(base_url)
        if host_is_reserved_or_non_public(host):
            raise HTTPException(status_code=400, detail="base_url_not_allowed_host")
        allowed = self.allowed_hosts()
        if allowed and host not in allowed:
            raise HTTPException(status_code=400, detail="base_url_not_monitored_domain")
        return base_url

    def quarantine_disallowed_tests(self) -> int:
        """Disable persisted tests that violate the current strict policy.

        Returns:
            The number of tests newly disabled.
        """
        if not self.settings.strict_base_url_policy:
            return 0
        summary = dbm.status_summary(self.settings)
        raw_tests = summary.get("tests")
        tests = raw_tests if isinstance(raw_tests, list) else []
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
            disabled = dbm.set_test_disabled(
                self.settings,
                dbm.TestDisableChange(
                    tenant_id=tenant_id,
                    test_id=test_id,
                    disabled=True,
                    reason=f"auto-disabled disallowed base_url host: {host or 'unknown'}",
                    until_ts=None,
                ),
            )
            changed += int(disabled)
        return changed
