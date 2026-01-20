CHECK = {
    "domain": "deplanbook.com",
    "url": "https://deplanbook.com",
    "expected_title_contains": "Deplanbook",
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

