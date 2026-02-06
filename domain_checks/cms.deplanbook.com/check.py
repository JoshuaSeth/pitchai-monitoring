CHECK = {
    "domain": "cms.deplanbook.com",
    "url": "https://cms.deplanbook.com",
    "required_selectors_all": [
        {"selector": 'a[href="/admin/login/"]', "state": "attached"},
        {"selector": 'a[href="/boek/"]', "state": "attached"},
        {"selector": 'a[href="/lessen/"]', "state": "attached"},
    ],
    "required_text_all": [
        "Wagtail",
        "Django",
    ],
    "synthetic_transactions": [
        {
            "name": "open_admin_login",
            "steps": [
                {"type": "goto"},
                {"type": "click", "selector": "a[href=\"/admin/login/\"]"},
                {"type": "expect_url_contains", "value": "/admin/login"},
            ],
        }
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "not found",
    ],
}
