# Copyright (c) 2026 PitchAI. All rights reserved.
"""On-expand, allowlisted HTTP evidence for active monitoring incidents."""

from __future__ import annotations

import asyncio
import ipaddress
import runpy
import socket
import time
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

from httpx import AsyncClient, RequestError

from . import web_runtime
from .domain_runtime import (
    load_domain_spec_from_module_dict,
)
from .evidence_contracts import (
    EvidenceResponse,
    captured_contract,
    request_failure_contract,
)
from .json_types import (
    json_object,
    object_list,
    optional_object,
    text_value,
)
from .safe_evidence import safe_public_url
from .serialization_runtime import load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping
    from dataclasses import dataclass

    from httpx import Response

    from .domain_runtime import DomainCheckSpec
    from .json_types import JsonInput, JsonObject
    from .registry_runtime import RegistrySettings

    @dataclass(frozen=True)
    class _RegistryState:
        settings: RegistrySettings

    @dataclass(frozen=True)
    class _RegistryApplication:
        state: _RegistryState


_HTTP_SUCCESS_MIN = 200
_HTTP_SUCCESS_MAX = 300
_ALLOWED_IDENTITY_DOMAIN = "pitchai.net"
_MAX_EMAIL_LENGTH = 254
_ASCII_VISIBLE_MIN = 33
_ASCII_VISIBLE_MAX = 126
_MAX_RESPONSE_BYTES = 8_192
_ALLOWED_PORTS = {80, 443}
router = web_runtime.router


def _load_config(path: Path) -> JsonObject:
    parsed = load_yaml(path.read_text(encoding="utf-8"))
    return json_object(parsed)


def _require_dashboard_identity(request: web_runtime.Request, settings: RegistrySettings) -> None:
    raw = request.headers.get(settings.dashboard_identity_header)
    if raw is None or raw != raw.strip() or len(raw) > _MAX_EMAIL_LENGTH:
        raise web_runtime.HTTPException(status_code=401, detail="PitchAI Entra SSO identity required")
    email = raw.lower()
    local_part, separator, domain = email.rpartition("@")
    invalid = (
        email.count("@") != 1
        or separator != "@"
        or not local_part
        or domain != _ALLOWED_IDENTITY_DOMAIN
        or any(ord(character) < _ASCII_VISIBLE_MIN or ord(character) > _ASCII_VISIBLE_MAX for character in email)
    )
    if invalid:
        raise web_runtime.HTTPException(status_code=401, detail="PitchAI Entra SSO identity required")


def _domain_entry(config: JsonObject, domain: str) -> JsonObject:
    for entry in object_list(config.get("domains")):
        if text_value(entry.get("domain")).lower() == domain:
            if entry.get("disabled") is True or entry.get("enabled") is False:
                raise web_runtime.HTTPException(status_code=409, detail="monitoring check is disabled")
            return entry
    raise web_runtime.HTTPException(status_code=404, detail="domain is not in the active monitoring inventory")


def _load_spec(entry: JsonObject, *, config_path: Path) -> DomainCheckSpec:
    domain = text_value(entry.get("domain"))
    plugin_path = config_path.parent / domain / "check.py"
    if plugin_path.is_file():
        module = cast("Mapping[str, object]", runpy.run_path(str(plugin_path)))
        plugin_check = json_object(cast("JsonInput", module.get("CHECK")))
        return load_domain_spec_from_module_dict({"CHECK": plugin_check})
    inline = optional_object(entry.get("check"))
    if inline:
        check: JsonObject = {"domain": domain}
        check.update(inline)
        return load_domain_spec_from_module_dict({"CHECK": check})
    message = "active monitoring check has no executable HTTP specification"
    raise web_runtime.HTTPException(status_code=503, detail=message)


def _status_is_expected(spec: DomainCheckSpec, status_code: int) -> bool:
    if spec.allowed_status_codes is not None:
        return status_code in spec.allowed_status_codes
    return _HTTP_SUCCESS_MIN <= status_code < _HTTP_SUCCESS_MAX


async def require_public_endpoint(url: str, *, inventory_domain: str) -> None:
    """Require an exact inventory hostname resolving only to public addresses.

    Raises:
        web_runtime.HTTPException: If the endpoint is not an allowlisted public target.
    """
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    invalid = (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or hostname != inventory_domain
        or port not in _ALLOWED_PORTS
        or safe_public_url(url) is None
    )
    if invalid:
        raise web_runtime.HTTPException(
            status_code=409,
            detail="monitoring evidence endpoint is not public and allowlisted",
        )
    addresses = await asyncio.get_running_loop().getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )
    resolved = {item[4][0] for item in addresses}
    if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
        raise web_runtime.HTTPException(
            status_code=409,
            detail="monitoring evidence endpoint resolved outside public IP space",
        )


async def bounded_response_body(response: Response) -> bytes:
    """Read no more than the evidence response byte budget.

    Returns:
        At most the configured number of response bytes.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        remaining = _MAX_RESPONSE_BYTES - size
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        size += min(len(chunk), remaining)
        if len(chunk) > remaining:
            break
    return b"".join(chunks)


async def _fetch_evidence(spec: DomainCheckSpec, *, timeout_seconds: float) -> EvidenceResponse:
    client_factory = partial(
        AsyncClient,
        follow_redirects=False,
        timeout=timeout_seconds,
        trust_env=False,
    )
    async with (
        client_factory() as client,
        client.stream("GET", spec.url) as response,
    ):
        content_type = cast("str | None", response.headers.get("content-type"))
        status_expected = _status_is_expected(spec, response.status_code)
        response_body = await bounded_response_body(response) if not status_expected else b""
        return EvidenceResponse(
            content_type=content_type,
            status_expected=status_expected,
            response_body=response_body,
            status_code=response.status_code,
            final_url=response.url,
        )


def _request_spec(domain: str, request: web_runtime.Request) -> tuple[DomainCheckSpec, str]:
    application = cast("_RegistryApplication", cast("object", request.app))
    settings = application.state.settings
    _require_dashboard_identity(request, settings)
    normalized_domain = domain.strip().lower().rstrip(".")
    config_path = Path(settings.monitor_config_path)
    entry = _domain_entry(_load_config(config_path), normalized_domain)
    return _load_spec(entry, config_path=config_path), normalized_domain


async def _validated_evidence(
    spec: DomainCheckSpec,
    *,
    normalized_domain: str,
    timeout_seconds: float,
) -> EvidenceResponse:
    await require_public_endpoint(spec.url, inventory_domain=normalized_domain)
    return await _fetch_evidence(spec, timeout_seconds=timeout_seconds)


@router.get(
    "/dashboard/api/v1/monitoring/incidents/{domain}/evidence",
    response_model=None,
)
async def incident_evidence(domain: str, request: web_runtime.Request) -> JsonObject:
    """Fetch one allowlisted public response only when an operator expands it.

    Returns:
        Sanitized public HTTP evidence with no response headers or credentials.

    Raises:
        web_runtime.HTTPException: If identity, inventory, or public-endpoint validation fails.
    """
    spec, normalized_domain = _request_spec(domain, request)
    observed_at = time.time()
    timeout_seconds = min(8.0, max(1.0, float(spec.http_timeout_seconds)))
    try:
        evidence = await _validated_evidence(
            spec,
            normalized_domain=normalized_domain,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as error:
        raise web_runtime.HTTPException(
            status_code=409,
            detail="monitoring evidence endpoint has an invalid port",
        ) from error
    except OSError as error:
        raise web_runtime.HTTPException(
            status_code=503,
            detail="monitoring evidence hostname did not resolve",
        ) from error
    except RequestError as error:
        return request_failure_contract(error, observed_at=observed_at, url=spec.url)
    return captured_contract(evidence, observed_at=observed_at)
