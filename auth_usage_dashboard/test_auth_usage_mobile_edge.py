# Copyright (c) 2026 PitchAI. All rights reserved.
"""Native reverse-proxy credential-isolation regression coverage."""

from __future__ import annotations

from pathlib import Path

from ._timeseries_test_fixtures import check


def test_mobile_nginx_edge_clears_browser_credentials() -> None:
    """Keep browser and proxy credentials outside the native edge."""
    config = Path("ops/codexusage.pitchai.net.nginx.conf").read_text(
        encoding="utf-8",
    )
    mobile = config.split("location ^~ /api/v1/mobile/ {", 1)[1].split(
        "\n    }",
        1,
    )[0]
    check(
        'proxy_set_header Authorization "";' in mobile,
        "native edge clears authorization",
    )
    check('proxy_set_header Cookie "";' in mobile, "native edge clears cookie")
    check(
        'proxy_set_header X-PitchAI-Email "";' in mobile,
        "native edge clears identity",
    )
    check(
        "pitchai-sso-protected-location" not in mobile,
        "native edge excludes browser auth",
    )
    check(
        "limit_req zone=codex_usage_mobile" in mobile,
        "native edge rate limits requests",
    )
