# Copyright (c) 2026 PitchAI. All rights reserved.
"""Sanitized evidence records for the ASTRA catalog monitor."""

from __future__ import annotations

from .catalog_transport import CATALOG_PATH
from .json_types import JsonObject, JsonValue
from .types import AccountCheck, ModelMatch


def safety_evidence(provider_request_count: int) -> JsonObject:
    """Describe the code-enforced network boundary for an event."""
    return {
        "provider_request_count": provider_request_count,
        "provider_method_allowlist": ["GET"],
        "provider_path_allowlist": [CATALOG_PATH],
        "request_body_sent": False,
        "redirects_followed": False,
        "proxy_used": False,
        "cookies_used": False,
        "auth_refresh_attempted": False,
        "generation_attempted": False,
        "lease_attempted": False,
        "usage_endpoint_touched": False,
        "reset_or_entitlement_endpoint_touched": False,
        "confidence": "code-enforced exact method/origin/path/query allowlist",
    }


def _match_evidence(match: ModelMatch) -> JsonObject:
    """Return the credential-free fields for one catalog match.

    Returns:
        JSON-safe model match evidence.
    """
    return {
        "identifier": match.identifier,
        "matched_fields": list(match.matched_fields),
        "matched_values": list(match.matched_values),
    }


def account_check_event(cycle_index: int, check: AccountCheck) -> JsonObject:
    """Build a credential-free audit event for one account catalog request."""
    account = check.account
    status = "checked"
    if check.unavailable_reason is not None:
        status = "unavailable"
    elif check.error_code is not None:
        status = "error"
    matches: list[JsonValue] = []
    for match in check.matches:
        matches.append(_match_evidence(match))
    return {
        "event_type": "account_catalog_check",
        "timestamp_utc": check.checked_at_utc,
        "cycle_index": cycle_index,
        "account_label": account.label,
        "account_fingerprint": account.fingerprint,
        "account_enabled": account.enabled,
        "broker_availability": account.availability,
        "auth_source": str(account.auth_path),
        "auth_source_kind": "broker-owned auth.json tokens access bearer",
        "auth_file_mode": account.auth_file_mode,
        "auth_file_mtime_utc": account.auth_file_mtime_utc,
        "account_identity_source": account.account_id_source,
        "catalog_check_status": status,
        "unavailable_reason": check.unavailable_reason,
        "model_count": check.model_count,
        "astra_present": bool(check.matches),
        "astra_matches": matches,
        "error_code": check.error_code,
        "safety": safety_evidence(check.provider_request_count),
    }
