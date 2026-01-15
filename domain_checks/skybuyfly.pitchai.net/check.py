CHECK = {
    "domain": "skybuyfly.pitchai.net",
    "url": "https://skybuyfly.pitchai.net",
    "expected_title_contains": "SkyBuyFly",
    "required_selectors_all": [
        {"selector": "meta[property=\"og:title\"]", "state": "attached"},
    ],
    "required_text_all": [
        "SkyBuyFly",
    ],
    "forbidden_text_any": [
        "maintenance",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    ],
}
