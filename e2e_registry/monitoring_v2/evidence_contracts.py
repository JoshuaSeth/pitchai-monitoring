# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sanitized dashboard contracts for on-expand monitoring evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_checks.monitoring_contracts.safe_evidence import safe_public_url, safe_response_excerpt, safe_text_excerpt

if TYPE_CHECKING:
    from httpx import URL

    from domain_checks.monitoring_contracts.json_types import JsonObject


@dataclass(frozen=True)
class EvidenceResponse:
    """Bounded response fields allowed into incident evidence."""

    content_type: str | None
    status_expected: bool
    response_body: bytes
    status_code: int
    final_url: URL


def request_failure_contract(error: BaseException, *, observed_at: float, url: str) -> JsonObject:
    """Return a sanitized contract for a failed public evidence request."""
    return {
        "ok": True,
        "data_state": "request_failed",
        "observed_at_ts": observed_at,
        "affected_check": "on-expand public HTTP evidence",
        "status_code": None,
        "error_message": safe_text_excerpt(error, max_chars=360),
        "response_excerpt": None,
        "content_type": None,
        "final_url": safe_public_url(url),
        "polling": {"trigger": "operator_expand", "background_probes": 0},
    }


def captured_contract(evidence: EvidenceResponse, *, observed_at: float) -> JsonObject:
    """Return a sanitized contract for one completed public evidence request."""
    excerpt = None
    if not evidence.status_expected:
        response_text = evidence.response_body.decode("utf-8", errors="replace")
        excerpt = safe_response_excerpt(response_text, content_type=evidence.content_type, max_chars=360)
    return {
        "ok": True,
        "data_state": "recovered" if evidence.status_expected else "captured",
        "observed_at_ts": observed_at,
        "affected_check": "on-expand public HTTP evidence",
        "status_code": evidence.status_code,
        "error_message": None if evidence.status_expected else f"unexpected_status: HTTP {evidence.status_code}",
        "response_excerpt": excerpt,
        "content_type": safe_text_excerpt(evidence.content_type, max_chars=120),
        "final_url": safe_public_url(evidence.final_url),
        "polling": {"trigger": "operator_expand", "background_probes": 0},
    }
