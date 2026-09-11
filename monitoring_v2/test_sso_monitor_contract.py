# Copyright (c) 2026 PitchAI. All rights reserved.
"""Keep Entra SSO monitoring on the owned redirect contract."""

from __future__ import annotations

from .domain_runtime import load_domain_spec
from .inventory import production_domains
from .json_types import optional_object, text_value
from .testing_runtime import pytest

_ENTRA_HOST_SUFFIX = "login.microsoftonline.com"
_MINIMUM_SSO_EDGE_COUNT = 10
_MINIMUM_HTTP_TIMEOUT_SECONDS = 30.0


def test_entra_sso_edges_do_not_render_the_third_party_login_shell() -> None:
    """Check redirect ownership without making Microsoft rendering a health gate."""
    domain_entries = production_domains()
    entries_with_checks = ((entry, optional_object(entry.get("check"))) for entry in domain_entries)
    entra_entries_with_checks = (
        pair
        for pair in entries_with_checks
        if text_value(pair[1].get("expected_final_host_suffix")) == _ENTRA_HOST_SUFFIX
    )
    entra_entries = (entry for entry, _check in entra_entries_with_checks)
    entra_specs = [load_domain_spec(entry) for entry in entra_entries]
    entra_domains = {specification.domain for specification in entra_specs}

    if "crm.pitchai.net" not in entra_domains:
        pytest.fail("CRM is missing its Entra redirect contract")
    if len(entra_specs) < _MINIMUM_SSO_EDGE_COUNT:
        pytest.fail("Entra SSO inventory coverage unexpectedly shrank")
    if any(specification.browser_enabled for specification in entra_specs):
        pytest.fail("an Entra SSO edge still renders the third-party login shell")
    if any(specification.http_timeout_seconds < _MINIMUM_HTTP_TIMEOUT_SECONDS for specification in entra_specs):
        pytest.fail("an Entra SSO edge lost the resilient HTTP timeout")
