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
