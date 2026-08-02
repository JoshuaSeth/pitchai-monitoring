from __future__ import annotations

import re
from pathlib import Path

from domain_checks.main import load_config, load_domain_spec


DOMAIN = "2fa-server.37.27.67.52.nip.io"


def _load_twofa_spec():
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domains = config.get("domains")
    assert isinstance(domains, list)
    entry = next(
        (item for item in domains if isinstance(item, dict) and item.get("domain") == DOMAIN),
        None,
    )
    assert entry is not None
    assert entry.get("disabled") is not True
    return config, load_domain_spec(entry)


def test_twofa_health_and_event_bus_outbox_readiness_are_monitored() -> None:
    config, spec = _load_twofa_spec()

    assert spec.url == f"https://{DOMAIN}/healthz"
    assert spec.allowed_status_codes == [200]
    assert set(spec.required_text_all) == {"ok", "time_utc"}

    checks = {check["name"]: check for check in spec.api_contract_checks}
    assert set(checks) == {"health", "event_bus_outbox_readiness"}
    assert checks["health"]["path"] == "/healthz"
    assert checks["event_bus_outbox_readiness"]["path"] == "/readyz"
    for check in checks.values():
        assert check["method"] == "GET"
        assert check["expected_status_codes"] == [200]
        assert check["expected_content_type_contains"] == "application/json"
        assert check["json_paths_equal"] == {"ok": True}
        assert check["json_paths_required"] == ["ok", "time_utc"]
        assert "headers" not in check

    container_config = config.get("container_health")
    assert isinstance(container_config, dict)
    patterns = container_config.get("include_name_patterns")
    assert isinstance(patterns, list)
    assert any(re.fullmatch(pattern, "twofa-server-prod") for pattern in patterns)
