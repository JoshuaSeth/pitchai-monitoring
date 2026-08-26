# Copyright (c) 2026 PitchAI. All rights reserved.
"""Bounded production-routing resolution for database alert eligibility."""

from __future__ import annotations

import re
from contextlib import closing
from dataclasses import dataclass
from http.client import HTTPSConnection
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from .models import RoutingPolicy, TrafficState

_MAX_ROUTING_FILE_BYTES = 16_384
_HTTP_STATUS_MIN = 200
_HTTP_STATUS_MAX = 400
_WEIGHT_TOTAL = 100
_COMMENT = re.compile(r"#.*$")
_PORT_REFERENCE = re.compile(r"(?:127\.0\.0\.1|localhost):(?P<port>[1-9][0-9]{1,4})")


class RoutingResolutionError(RuntimeError):
    """A configured routing source did not provide unambiguous traffic truth."""


@dataclass(frozen=True)
class RoutingResolution:
    """Sanitized routing truth for one policy in one collector cycle."""

    policy_id: str
    weights: tuple[tuple[str, int], ...]
    source_label: str
    error_class: str | None

    def slot_state(self, slot: str) -> tuple[TrafficState, int | None]:
        """Return active/inactive/unknown state for one configured slot."""
        if self.error_class is not None:
            return "unknown", None
        weights = dict(self.weights)
        if slot not in weights:
            return "unknown", None
        weight = weights[slot]
        return ("active" if weight > 0 else "inactive"), weight


def _parse_weight_header(value: str, *, slots: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    weights: dict[str, int] = {}
    for raw_part in re.split(r"[,;]", value):
        name, separator, raw_weight = raw_part.strip().partition("=")
        if not separator or name not in slots or not raw_weight.isdigit():
            message = "routing_weight_header_invalid"
            raise RoutingResolutionError(message)
        weight = int(raw_weight)
        if weight > _WEIGHT_TOTAL or name in weights:
            message = "routing_weight_header_invalid"
            raise RoutingResolutionError(message)
        weights[name] = weight
    if set(weights) != set(slots) or sum(weights.values()) != _WEIGHT_TOTAL:
        message = "routing_weight_header_incomplete"
        raise RoutingResolutionError(message)
    if not any(weight > 0 for weight in weights.values()):
        message = "routing_weight_header_has_no_active_slot"
        raise RoutingResolutionError(message)
    return tuple((slot, weights[slot]) for slot in slots)


def _header_weights(policy: RoutingPolicy, *, timeout_seconds: float) -> tuple[tuple[str, int], ...]:
    parsed = urlsplit(policy.source)
    host = parsed.hostname
    header_name = policy.header_name
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        message = "routing_header_source_invalid"
        raise RoutingResolutionError(message)
    if host is None or header_name is None:
        message = "routing_header_source_invalid"
        raise RoutingResolutionError(message)
    path = parsed.path or "/"
    connection = HTTPSConnection(host, port=parsed.port, timeout=timeout_seconds)
    with closing(connection):
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/plain",
                "Range": "bytes=0-0",
                "User-Agent": "PitchAI-DB-Monitor/1",
            },
        )
        response = connection.getresponse()
        if not _HTTP_STATUS_MIN <= response.status < _HTTP_STATUS_MAX:
            message = "routing_header_http_status"
            raise RoutingResolutionError(message)
        header = response.getheader(header_name)
        if header is None:
            message = "routing_header_missing"
            raise RoutingResolutionError(message)
        return _parse_weight_header(header, slots=policy.slots)


def _bounded_file(path: Path) -> str:
    with path.open("rb") as stream:
        payload = stream.read(_MAX_ROUTING_FILE_BYTES + 1)
    if len(payload) > _MAX_ROUTING_FILE_BYTES:
        message = "routing_file_too_large"
        raise RoutingResolutionError(message)
    return payload.decode("utf-8")


def _file_weights(policy: RoutingPolicy) -> tuple[tuple[str, int], ...]:
    bounded_text = _bounded_file(Path(policy.source))
    source_lines = bounded_text.splitlines()
    uncommented_lines = (_COMMENT.sub("", line) for line in source_lines)
    text = "\n".join(uncommented_lines)
    ports: set[int] = set()
    ports.update(int(match.group("port")) for match in _PORT_REFERENCE.finditer(text))
    configured = dict(policy.slot_ports)
    matching_slots: list[str] = []
    for slot, port in configured.items():
        if port in ports:
            matching_slots.append(slot)
    if len(matching_slots) != 1:
        message = "routing_file_active_slot_ambiguous"
        raise RoutingResolutionError(message)
    active = matching_slots[0]
    return tuple((slot, _WEIGHT_TOTAL if slot == active else 0) for slot in policy.slots)


def resolve_routing(
    policies: tuple[RoutingPolicy, ...],
    *,
    timeout_seconds: float,
) -> dict[str, RoutingResolution]:
    """Resolve every configured routing policy from production routing truth.

    Returns:
        Current slot weights indexed by routing-policy id.
    """
    resolutions: dict[str, RoutingResolution] = {}
    for policy in policies:
        weights = (
            _header_weights(policy, timeout_seconds=timeout_seconds)
            if policy.kind == "http_header"
            else _file_weights(policy)
        )
        resolution = RoutingResolution(
            policy_id=policy.policy_id,
            weights=weights,
            source_label=policy.kind,
            error_class=None,
        )
        resolutions[policy.policy_id] = resolution
    return resolutions
