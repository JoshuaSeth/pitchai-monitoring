"""Check TLS and private ingress only; authenticated dependency health is separate."""

CHECK = {
    "domain": "orthoparse-labs-staging.135-181-182-48.sslip.io",
    "url": "https://orthoparse-labs-staging.135-181-182-48.sslip.io/healthz",
    "allowed_status_codes": [401],
    "browser_enabled": False,
    "expected_final_host_suffix": "orthoparse-labs-staging.135-181-182-48.sslip.io",
    "expected_final_path": "/healthz",
    "expected_title_contains": "401 Authorization Required",
    "required_text_all": ["401 Authorization Required"],
    "forbidden_text_any": ["bad gateway", "service unavailable", "gateway timeout"],
}
