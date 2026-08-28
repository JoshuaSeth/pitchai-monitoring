from __future__ import annotations

import pytest

from domain_checks.main import load_domain_spec


@pytest.mark.parametrize("domain", ["deplanbook.com", "dpb.pitchai.net"])
def test_diary_synthetic_verifies_anonymous_login_boundary(domain: str) -> None:
    spec = load_domain_spec(domain)

    assert spec.synthetic_transactions == [
        {
            "name": "open_diary_page",
            "steps": [
                {"type": "goto"},
                {"type": "click", "selector": 'a[href="/diary"]'},
                {"type": "expect_url_contains", "value": "/login-page?next=%2Fdiary"},
                {"type": "wait_for_selector", "selector": "text=Log in bij DePlanBook", "state": "visible"},
            ],
        }
    ]
