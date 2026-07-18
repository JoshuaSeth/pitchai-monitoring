from __future__ import annotations

from pathlib import Path

from domain_checks.main import load_config, load_domain_spec


def test_all_config_domains_have_check_specs() -> None:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domains = config.get("domains")
    assert isinstance(domains, list)
    assert domains, "config.yaml domains list is empty"

    specs = [load_domain_spec(entry) for entry in domains]
    assert len(specs) == len(domains)

    for spec in specs:
        assert spec.domain
        assert spec.url.startswith(("http://", "https://"))
        has_any_assertion = bool(
            spec.required_selectors_all
            or spec.required_selectors_any
            or spec.required_text_all
            or spec.expected_title_contains
        )
        assert has_any_assertion, f"{spec.domain} has no browser assertions"


def test_afasask_domains_are_enabled_and_check_expected_access_surfaces() -> None:
    config_path = Path(__file__).resolve().parents[1] / "domain_checks" / "config.yaml"
    config = load_config(config_path)
    domains = config.get("domains")
    assert isinstance(domains, list)

    entry = next((d for d in domains if isinstance(d, dict) and d.get("domain") == "afasask.gzb.nl"), None)
    assert entry is not None
    assert entry.get("disabled") is not True

    spec = load_domain_spec(entry)
    assert "mode=codex" in spec.url
    assert "intensity=medium" in spec.url
    assert any(item.selector == "#chat-input" for item in spec.required_selectors_all)
    assert any(item.selector == ".chat-submit" for item in spec.required_selectors_all)
    assert "Mislukt" not in spec.forbidden_text_any

    demo_entry = next(
        (d for d in domains if isinstance(d, dict) and d.get("domain") == "demo.afasask.pitchai.net"),
        None,
    )
    assert demo_entry is not None
    assert demo_entry.get("disabled") is not True

    demo_spec = load_domain_spec(demo_entry)
    assert "mode=codex" in demo_spec.url
    assert "intensity=fast" in demo_spec.url
    assert any("login-admin" in item.selector for item in demo_spec.required_selectors_all)
    assert not any(item.selector == "#chat-input" for item in demo_spec.required_selectors_all)
    assert any(
        step.get("type") == "expect_url_contains" and step.get("value") == "/login-page"
        for transaction in demo_spec.synthetic_transactions
        for step in transaction.get("steps", [])
    )
    assert any(check.get("name") == "codex_no_quota_readiness" for check in demo_spec.api_contract_checks)


def test_afasask_demo_canary_fails_fast_on_explicit_data_failure() -> None:
    """Keep rendered canary failures out of the generic 240-second timeout path."""
    source_path = Path(__file__).resolve().parents[1] / "e2e_tests" / "afasask_demo_codex_fast_ok.py"
    source = source_path.read_text(encoding="utf-8")

    assert '"afasask_demo_canary_fail"' in source
    assert "state.failureMarkers.some" in source
    assert "for marker in _FAILURE_MARKERS" in source
