from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _location(config: str, marker: str) -> str:
    start = config.index(marker)
    next_location = config.find("\n    location ", start + len(marker))
    return config[start:] if next_location == -1 else config[start:next_location]


def test_codex_usage_edge_uses_shared_entra_without_basic_fallback() -> None:
    config = (ROOT / "ops/codexusage.pitchai.net.nginx.conf").read_text(encoding="utf-8")

    assert "auth_basic" not in config
    assert "pitchai-sso-server-locations.inc" in config
    tls_server = config[config.index("    listen 443 ssl http2;") :]
    protected = _location(tls_server, "    location / {")
    assert "pitchai-sso-protected-location.inc" in protected
    assert "proxy_set_header X-PitchAI-Email" not in protected

    health = _location(config, "    location = /healthz {")
    assert 'proxy_set_header X-PitchAI-Email "";' in health
    assert 'proxy_set_header Authorization "";' in health


def test_monitoring_edge_separates_entra_browser_and_machine_auth() -> None:
    config = (ROOT / "ops/monitoring.pitchai.net.nginx.conf").read_text(encoding="utf-8")

    assert "auth_basic" not in config
    assert "pitchai-sso-server-locations.inc" in config

    machine = _location(config, "    location ^~ /api/v1/ {")
    assert "pitchai-sso-protected-location.inc" not in machine
    assert 'proxy_set_header X-PitchAI-Email "";' in machine
    assert 'proxy_set_header X-PitchAI-User "";' in machine
    assert 'proxy_set_header Authorization "";' not in machine

    tenant_ui = _location(config, "    location ^~ /ui/ {")
    assert "pitchai-sso-protected-location.inc" not in tenant_ui
    assert 'proxy_set_header X-PitchAI-Email "";' in tenant_ui

    tls_server = config[config.index("    listen 443 ssl http2;") :]
    protected = _location(tls_server, "    location / {")
    assert "pitchai-sso-protected-location.inc" in protected
    assert "proxy_set_header X-PitchAI-Email" not in protected
