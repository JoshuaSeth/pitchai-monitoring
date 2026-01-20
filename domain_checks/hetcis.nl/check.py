CHECK = {
    "domain": "hetcis.nl",
    "url": "https://hetcis.nl",
    "expected_title_contains": "Centrum voor",
    "expected_final_host_suffix": "hetcis.nl",
    "required_selectors_all": [
        {"selector": 'a[href="/over-ons"]', "state": "visible"},
        {"selector": 'a[href="/leren"]', "state": "visible"},
        {"selector": 'a[href="/contact"]', "state": "visible"},
    ],
}

