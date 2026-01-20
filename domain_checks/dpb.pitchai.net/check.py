CHECK = {
    "domain": "dpb.pitchai.net",
    "url": "https://dpb.pitchai.net",
    "expected_title_contains": "Deplanbook",
    "expected_final_host_suffix": "deplanbook.com",
    "required_selectors_all": [
        {"selector": "#main", "state": "visible"},
        {"selector": 'a[href="https://cms.deplanbook.com"]', "state": "attached"},
    ],
    "required_selectors_any": [
        {"selector": 'a[href="/login-page?next=/diary"]', "state": "attached"},
        {"selector": 'a[href="/diary"]', "state": "attached"},
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "not found",
    ],
}

