# Copyright (c) 2026 PitchAI. All rights reserved.
"""Protected App Attest routes for native iPhone and Watch clients."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from cryptography import x509
from cryptography.exceptions import InvalidSignature

from .mobile_auth_codec import CBOR_DECODE_ERROR
from .mobile_auth_errors import MobileAuthError, MobileAuthFailure
from .mobile_challenges import canonical_client_data
from .mobile_projection import build_mobile_snapshot
from .mobile_route_errors import (
    raise_auth_failure,
    raise_invalid_request,
    raise_mobile_error,
)
from .mobile_route_payloads import parse_assertion, parse_attestation, parse_challenge
from .mobile_web_runtime import (
    JSON_RESPONSE_FACTORY,
    ROUTER_FACTORY,
    runtime_route,
)

if TYPE_CHECKING:
    from .mobile_challenges import ChallengePurpose
    from .mobile_registry import AppAttestRegistry
    from .mobile_route_payloads import AssertionPayload, AttestationPayload, ChallengePayload
    from .mobile_route_state import MobileRouteConfiguration, MobileRouteDependencies, MobileStateContainer
    from .mobile_web_runtime import WebRequest, WebResponse
    from .timeseries_types import JsonObject

router = ROUTER_FACTORY()


@router.post("/api/v1/mobile/challenge", response_model=None)
@runtime_route
async def mobile_challenge(request: WebRequest) -> WebResponse:
    """Issue a purpose- and key-bound single-use challenge.

    Returns:
        A secret-free challenge response.
    """
    try:
        payload = parse_challenge(await _request_object(request))
    except (TypeError, ValueError) as error:
        raise_invalid_request(error)
    try:
        return _mobile_challenge(payload, _dependencies(request))
    except MobileAuthError as error:
        raise_mobile_error(error)


@router.post("/api/v1/mobile/attest", response_model=None)
@runtime_route
async def mobile_attest(request: WebRequest) -> WebResponse:
    """Consume an enrollment challenge and verify one attested key.

    Returns:
        A registration result after successful attestation.
    """
    try:
        payload = parse_attestation(await _request_object(request))
    except (TypeError, ValueError) as error:
        raise_invalid_request(error)
    try:
        return await _mobile_attest(payload, _dependencies(request))
    except MobileAuthError as error:
        raise_mobile_error(error)
    except (CBOR_DECODE_ERROR, InvalidSignature, TypeError, ValueError, x509.ExtensionNotFound) as error:
        raise_auth_failure(error, MobileAuthFailure.ATTESTATION_OBJECT_INVALID)


@router.post("/api/v1/mobile/capacity", response_model=None)
@runtime_route
async def mobile_capacity(request: WebRequest) -> WebResponse:
    """Return the secret-free capacity projection after an assertion.

    Returns:
        The current protected mobile capacity projection.
    """
    try:
        payload = parse_assertion(await _request_object(request))
    except (TypeError, ValueError) as error:
        raise_invalid_request(error)
    try:
        return await _mobile_capacity(payload, _dependencies(request))
    except MobileAuthError as error:
        raise_mobile_error(error)
    except InvalidSignature as error:
        raise_auth_failure(error, MobileAuthFailure.ASSERTION_SIGNATURE_INVALID)
    except (CBOR_DECODE_ERROR, TypeError, ValueError) as error:
        raise_auth_failure(error, MobileAuthFailure.ASSERTION_INVALID)


@router.post("/api/v1/mobile/refresh", response_model=None)
@runtime_route
async def mobile_refresh(request: WebRequest) -> WebResponse:
    """Request a bounded probe after an assertion and return safe state.

    Returns:
        The probe outcome and updated secret-free capacity projection.
    """
    try:
        payload = parse_assertion(await _request_object(request))
    except (TypeError, ValueError) as error:
        raise_invalid_request(error)
    try:
        return await _mobile_refresh(payload, _dependencies(request))
    except MobileAuthError as error:
        raise_mobile_error(error)
    except InvalidSignature as error:
        raise_auth_failure(error, MobileAuthFailure.ASSERTION_SIGNATURE_INVALID)
    except (CBOR_DECODE_ERROR, TypeError, ValueError) as error:
        raise_auth_failure(error, MobileAuthFailure.ASSERTION_INVALID)


def _mobile_challenge(
    payload: ChallengePayload,
    dependencies: MobileRouteDependencies,
) -> WebResponse:
    _authorize_challenge(payload, dependencies.registry)
    challenge = dependencies.challenges.issue(purpose=payload.purpose, key_id=payload.key_id)
    return JSON_RESPONSE_FACTORY(
        {
            "schema_version": 1,
            "challenge_id": challenge.identifier,
            "challenge": challenge.encoded_value,
            "expires_in_seconds": dependencies.configuration.challenge_ttl_seconds,
        },
    )


async def _mobile_attest(
    payload: AttestationPayload,
    dependencies: MobileRouteDependencies,
) -> WebResponse:
    challenge = dependencies.challenges.consume(
        identifier=payload.challenge_id,
        purpose="attest",
        key_id=payload.key_id,
    )
    await asyncio.to_thread(
        dependencies.registry.register,
        key_id=payload.key_id,
        attestation_object=payload.attestation,
        challenge=challenge.value,
    )
    return JSON_RESPONSE_FACTORY({"schema_version": 1, "registered": True})


async def _mobile_capacity(
    payload: AssertionPayload,
    dependencies: MobileRouteDependencies,
) -> WebResponse:
    await _verify_mobile_assertion(payload, purpose="capacity", dependencies=dependencies)
    snapshot = await dependencies.service.snapshot()
    return JSON_RESPONSE_FACTORY(_mobile_snapshot(snapshot, dependencies.configuration))


async def _mobile_refresh(
    payload: AssertionPayload,
    dependencies: MobileRouteDependencies,
) -> WebResponse:
    await _verify_mobile_assertion(payload, purpose="refresh", dependencies=dependencies)
    result = await dependencies.service.request_manual_probe()
    snapshot_value = result.get("snapshot")
    snapshot = snapshot_value if isinstance(snapshot_value, dict) else {}
    return JSON_RESPONSE_FACTORY(
        {
            "schema_version": 1,
            "probe_started": bool(result.get("probe_started")),
            "reason": result.get("reason"),
            "retry_after_seconds": result.get("retry_after_seconds"),
            "snapshot": _mobile_snapshot(snapshot, dependencies.configuration),
        },
    )


async def _verify_mobile_assertion(
    payload: AssertionPayload,
    *,
    purpose: ChallengePurpose,
    dependencies: MobileRouteDependencies,
) -> None:
    challenge = dependencies.challenges.consume(
        identifier=payload.challenge_id,
        purpose=purpose,
        key_id=payload.key_id,
    )
    _ = await asyncio.to_thread(
        dependencies.registry.verify_assertion,
        key_id=payload.key_id,
        assertion_object=payload.assertion,
        client_data=canonical_client_data(challenge),
    )


def _authorize_challenge(payload: ChallengePayload, registry: AppAttestRegistry) -> None:
    if payload.purpose == "attest":
        if registry.has_key(payload.key_id):
            raise MobileAuthError(MobileAuthFailure.KEY_ALREADY_REGISTERED)
        if not registry.enrollment_enabled:
            raise MobileAuthError(MobileAuthFailure.ENROLLMENT_CLOSED)
    elif not registry.has_key(payload.key_id):
        raise MobileAuthError(MobileAuthFailure.KEY_UNKNOWN)


def _dependencies(request: WebRequest) -> MobileRouteDependencies:
    dynamic_state = cast("object", request.app.state)
    state = cast("MobileStateContainer", dynamic_state)
    return state.mobile_route_dependencies


def _mobile_snapshot(snapshot: JsonObject, configuration: MobileRouteConfiguration) -> JsonObject:
    return build_mobile_snapshot(
        snapshot,
        manual_refresh_min_interval_seconds=configuration.manual_refresh_min_interval_seconds,
        recommended_background_refresh_seconds=configuration.background_refresh_seconds,
    )


async def _request_object(request: WebRequest) -> JsonObject:
    value = await request.json()
    if not isinstance(value, dict):
        raise TypeError
    return value
