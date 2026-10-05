# Copyright (c) 2026 PitchAI. All rights reserved.
"""Secret-safe HTTP error translation for native App Attest routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

from .mobile_auth_errors import MobileAuthError
from .mobile_web_runtime import HTTP_EXCEPTION_FACTORY

if TYPE_CHECKING:
    from .mobile_auth_errors import MobileAuthFailure
    from .timeseries_types import JsonObject


def raise_mobile_error(error: MobileAuthError) -> Never:
    """Translate one stable native-auth failure into an HTTP response.

    Raises:
        HTTP_EXCEPTION_FACTORY: Always, with a secret-safe error response.
    """
    status_code = _mobile_error_status(error.code)
    detail: JsonObject = {"code": error.code, "message": error.detail}
    raise HTTP_EXCEPTION_FACTORY(status_code=status_code, detail=detail) from error


def raise_invalid_request(error: Exception) -> Never:
    """Translate one malformed native JSON request without leaking detail.

    Raises:
        HTTP_EXCEPTION_FACTORY: Always, with a secret-safe error response.
    """
    detail: JsonObject = {
        "code": "invalid_request",
        "message": "Native request payload is invalid",
    }
    raise HTTP_EXCEPTION_FACTORY(status_code=422, detail=detail) from error


def raise_auth_failure(error: Exception, failure: MobileAuthFailure) -> Never:
    """Translate one raw cryptographic failure at the HTTP boundary.

    Raises:
        HTTP_EXCEPTION_FACTORY: Always, with a secret-safe error response.
    """
    auth_error = MobileAuthError(failure)
    status_code = _mobile_error_status(auth_error.code)
    detail: JsonObject = {"code": auth_error.code, "message": auth_error.detail}
    raise HTTP_EXCEPTION_FACTORY(status_code=status_code, detail=detail) from error


def _mobile_error_status(code: str) -> int:
    if code in {"enrollment_closed", "key_limit"}:
        return 403
    if code == "key_already_registered":
        return 409
    if code == "challenge_capacity":
        return 429
    protected_prefixes = (
        "challenge_",
        "key_",
        "attestation_",
        "assertion_",
        "base64_",
        "cbor_",
    )
    return 401 if code.startswith(protected_prefixes) else 400
