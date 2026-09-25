# Copyright (c) 2026 PitchAI. All rights reserved.
"""Lock the Entra browser and machine-auth edge routing contracts."""

from __future__ import annotations

from pathlib import Path

from domain_checks.testing import verify

ROOT = Path(__file__).resolve().parents[1]


def _location(config: str, marker: str) -> str:
    """Return one Nginx location block beginning at ``marker``."""
    start = config.index(marker)
    next_location = config.find("\n    location ", start + len(marker))
    return config[start:] if next_location == -1 else config[start:next_location]


def test_codex_usage_edge_uses_shared_entra_without_basic_fallback() -> None:
    """Keep the Codex usage browser route on the shared Entra edge."""
    config = (ROOT / "ops/codexusage.pitchai.net.nginx.conf").read_text(encoding="utf-8")

    verify("auth_basic" not in config)
    verify("pitchai-sso-server-locations.inc" in config)
    tls_server = config[config.index("    listen 443 ssl http2;") :]
    protected = _location(tls_server, "    location / {")
    verify("pitchai-sso-protected-location.inc" in protected)
    verify("proxy_set_header X-PitchAI-Email" not in protected)

    health = _location(config, "    location = /healthz {")
    verify('proxy_set_header X-PitchAI-Email "";' in health)
    verify('proxy_set_header Authorization "";' in health)


def test_monitoring_edge_separates_entra_browser_and_machine_auth() -> None:
    """Keep browser SSO separate from monitoring's machine-auth routes."""
    config = (ROOT / "ops/monitoring.pitchai.net.nginx.conf").read_text(encoding="utf-8")

    verify("auth_basic" not in config)
    verify("pitchai-sso-server-locations.inc" in config)

    machine = _location(config, "    location ^~ /api/v1/ {")
    verify("pitchai-sso-protected-location.inc" not in machine)
    verify('proxy_set_header X-PitchAI-Email "";' in machine)
    verify('proxy_set_header X-PitchAI-User "";' in machine)
    verify('proxy_set_header Authorization "";' not in machine)

    tenant_ui = _location(config, "    location ^~ /ui/ {")
    verify("pitchai-sso-protected-location.inc" not in tenant_ui)
    verify('proxy_set_header X-PitchAI-Email "";' in tenant_ui)

    tls_server = config[config.index("    listen 443 ssl http2;") :]
    protected = _location(tls_server, "    location / {")
    verify("pitchai-sso-protected-location.inc" in protected)
    verify("proxy_set_header X-PitchAI-Email" not in protected)
