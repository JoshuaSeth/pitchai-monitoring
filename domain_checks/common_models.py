# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable typed models for HTTP and browser domain checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple, NotRequired, TypedDict, Unpack

if TYPE_CHECKING:
    from domain_checks.types import JsonObject

type SelectorState = Literal["attached", "detached", "hidden", "visible"]

DEFAULT_MAINTENANCE_TEXT = [
    "maintenance",
    "temporarily unavailable",
    "we'll be back",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
]


@dataclass(frozen=True)
class SelectorCheck:
    """Describe one Playwright selector assertion."""

    selector: str
    state: SelectorState = "visible"


class DomainCheckSpecOptions(TypedDict):
    """Optional keyword fields accepted by ``DomainCheckSpec``."""

    allowed_status_codes: NotRequired[list[int] | None]
    expected_title_contains: NotRequired[str | None]
    expected_final_host_suffix: NotRequired[str | None]
    required_selectors_all: NotRequired[list[SelectorCheck]]
    required_selectors_any: NotRequired[list[SelectorCheck]]
    required_text_all: NotRequired[list[str]]
    forbidden_text_any: NotRequired[list[str]]
    capture_headers: NotRequired[list[str]]
    api_contract_checks: NotRequired[list[JsonObject]]
    synthetic_transactions: NotRequired[list[JsonObject]]
    web_vitals: NotRequired[JsonObject]
    proxy: NotRequired[JsonObject]
    browser_enabled: NotRequired[bool]
    http_timeout_seconds: NotRequired[float]
    browser_timeout_seconds: NotRequired[float]


class _DomainCheckSpecValues(NamedTuple):
    domain: str
    url: str
    allowed_status_codes: list[int] | None
    expected_title_contains: str | None
    expected_final_host_suffix: str | None
    required_selectors_all: list[SelectorCheck]
    required_selectors_any: list[SelectorCheck]
    required_text_all: list[str]
    forbidden_text_any: list[str]
    capture_headers: list[str]
    api_contract_checks: list[JsonObject]
    synthetic_transactions: list[JsonObject]
    web_vitals: JsonObject
    proxy: JsonObject
    browser_enabled: bool
    http_timeout_seconds: float
    browser_timeout_seconds: float


@dataclass(frozen=True, init=False)
class DomainCheckSpec:
    """Describe one complete domain-monitor contract."""

    _values: _DomainCheckSpecValues

    def __init__(
        self,
        domain: str,
        url: str,
        **options: Unpack[DomainCheckSpecOptions],
    ) -> None:
        """Create a contract while retaining the historical keyword API."""
        values = _DomainCheckSpecValues(
            domain=domain,
            url=url,
            allowed_status_codes=options.get("allowed_status_codes"),
            expected_title_contains=options.get("expected_title_contains"),
            expected_final_host_suffix=options.get("expected_final_host_suffix"),
            required_selectors_all=options.get("required_selectors_all", []),
            required_selectors_any=options.get("required_selectors_any", []),
            required_text_all=options.get("required_text_all", []),
            forbidden_text_any=options.get(
                "forbidden_text_any",
                list(DEFAULT_MAINTENANCE_TEXT),
            ),
            capture_headers=options.get("capture_headers", []),
            api_contract_checks=options.get("api_contract_checks", []),
            synthetic_transactions=options.get("synthetic_transactions", []),
            web_vitals=options.get("web_vitals", {}),
            proxy=options.get("proxy", {}),
            browser_enabled=options.get("browser_enabled", True),
            http_timeout_seconds=options.get("http_timeout_seconds", 15.0),
            browser_timeout_seconds=options.get("browser_timeout_seconds", 25.0),
        )
        object.__setattr__(self, "_values", values)

    @property
    def domain(self) -> str:
        """Return the normalized domain identity."""
        return self._values.domain

    @property
    def url(self) -> str:
        """Return the URL to check."""
        return self._values.url

    @property
    def allowed_status_codes(self) -> list[int] | None:
        """Return explicit allowed HTTP status codes."""
        return self._values.allowed_status_codes

    @property
    def expected_title_contains(self) -> str | None:
        """Return the required title fragment."""
        return self._values.expected_title_contains

    @property
    def expected_final_host_suffix(self) -> str | None:
        """Return the required final hostname suffix."""
        return self._values.expected_final_host_suffix

    @property
    def required_selectors_all(self) -> list[SelectorCheck]:
        """Return selectors that must all satisfy their state."""
        return self._values.required_selectors_all

    @property
    def required_selectors_any(self) -> list[SelectorCheck]:
        """Return selectors where at least one must satisfy its state."""
        return self._values.required_selectors_any

    @property
    def required_text_all(self) -> list[str]:
        """Return visible text fragments that must all be present."""
        return self._values.required_text_all

    @property
    def forbidden_text_any(self) -> list[str]:
        """Return visible text fragments that must be absent."""
        return self._values.forbidden_text_any

    @property
    def capture_headers(self) -> list[str]:
        """Return response headers safe to capture."""
        return self._values.capture_headers

    @property
    def api_contract_checks(self) -> list[JsonObject]:
        """Return configured API contract checks."""
        return self._values.api_contract_checks

    @property
    def synthetic_transactions(self) -> list[JsonObject]:
        """Return configured synthetic transactions."""
        return self._values.synthetic_transactions

    @property
    def web_vitals(self) -> JsonObject:
        """Return web-vitals settings."""
        return self._values.web_vitals

    @property
    def proxy(self) -> JsonObject:
        """Return proxy settings."""
        return self._values.proxy

    @property
    def browser_enabled(self) -> bool:
        """Return whether browser assertions apply."""
        return self._values.browser_enabled

    @property
    def http_timeout_seconds(self) -> float:
        """Return the HTTP timeout."""
        return self._values.http_timeout_seconds

    @property
    def browser_timeout_seconds(self) -> float:
        """Return the browser timeout."""
        return self._values.browser_timeout_seconds


@dataclass(frozen=True)
class DomainCheckResult:
    """Describe one domain check outcome."""

    domain: str
    ok: bool
    reason: str
    details: JsonObject
