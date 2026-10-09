# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitor HetCIS request validation without uploading files or sending mail."""

from __future__ import annotations

from .domain_runtime import inventory_runtime, load_domain_spec
from .inventory import entry_by_domain
from .json_types import optional_object, text_value
from .testing_runtime import pytest


def test_hetcis_backend_checks_are_read_only_and_alias_is_quiet() -> None:
    """Pin the deployed validation responses and independent incident sources."""
    expected = {
        "upload-to-wasabi-7v37bcjssa-uc.a.run.app": ("/", 403, "origin_required", True),
        "us-central1-cis-db-e9fd3.cloudfunctions.net": (
            "/upload_to_wasabi", 403, "origin_required", False,
        ),
        "submit-maatje-form-7v37bcjssa-uc.a.run.app": ("/", 400, "INVALID_ARGUMENT", True),
    }
    for domain, (path, status, identity, alertable) in expected.items():
        entry = entry_by_domain(domain)
        spec = load_domain_spec(entry)
        check = optional_object(entry.get("check"))
        policy = inventory_runtime.parse_domain_alert_policy(entry)
        if spec.url != f"https://{domain}{path}" or spec.allowed_status_codes != [status]:
            pytest.fail(f"HetCIS validation route changed: {domain}")
        if spec.browser_enabled or identity not in spec.required_text_all:
            pytest.fail(f"HetCIS credential-free response contract changed: {domain}")
        if text_value(check.get("expected_final_host_suffix")) != domain:
            pytest.fail(f"HetCIS validation must not redirect elsewhere: {domain}")
        if check.get("api_contract") or check.get("synthetic"):
            pytest.fail(f"HetCIS availability probe gained a transaction: {domain}")
        if policy.telegram_enabled != alertable:
            pytest.fail(f"HetCIS primary/alias incident policy changed: {domain}")
        if not alertable and (policy.telegram != "dashboard-only" or not policy.reason):
            pytest.fail("HetCIS upload alias lost its explicit quiet reason")


def test_production_azure_resource_is_alertable_and_unauthenticated() -> None:
    """Monitor the configured production provider without model calls."""
    domain = "dft-openai-info.openai.azure.com"
    entry = entry_by_domain(domain)
    spec = load_domain_spec(entry)
    policy = inventory_runtime.parse_domain_alert_policy(entry)
    check = optional_object(entry.get("check"))
    if spec.url != f"https://{domain}/" or spec.allowed_status_codes != [200]:
        pytest.fail("production Azure resource lost its read-only root check")
    if spec.browser_enabled or check.get("api_contract") or check.get("synthetic"):
        pytest.fail("production Azure resource gained an interactive transaction")
    if not policy.telegram_enabled or policy.telegram != "critical":
        pytest.fail("production Azure provider lost normal incident behavior")
    if text_value(entry.get("environment")) != "production":
        pytest.fail("configured production Azure provider was demoted")
