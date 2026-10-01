# Copyright (c) 2026 PitchAI. All rights reserved.
"""CLI and environment resolution for one monitoring service health probe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from .service_health_evidence import optional_env_text, positive_env_integer, sanitize_fragment
from .service_health_roles import ProgressBudget, UsageError, role_spec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .service_health_roles import RoleSpec

_REGISTRY_ROLE: Final = "registry"
_DEFAULT_REGISTRY_PORT: Final = 8111


@dataclass(frozen=True)
class HealthProbeRequest:
    """One resolved, role-aware health probe request.

    Attributes:
        role: Role name accepted by ``--role``.
        service: Deployed container the role runs in.
        evidence_path: Resolved evidence document for this container.
        budget: Freshness thresholds after CLI and environment overrides.
        probe_url: Container-local liveness endpoint, empty when unused.
        missing_reason: Reason code used while the evidence is still absent.
    """

    role: str
    service: str
    evidence_path: Path
    budget: ProgressBudget
    probe_url: str
    missing_reason: str


def parse_request(argv: Sequence[str]) -> HealthProbeRequest:
    """Return the probe request described by the CLI arguments and environment.

    Args:
        argv: Arguments after the module name, e.g. ``--role monitor``.

    Returns:
        The resolved request for one deployed role.
    """
    values = _cli_values(argv)
    spec = role_spec(values.get("--role", ""))
    evidence = values.get("--evidence") or optional_env_text(spec.evidence_env, spec.evidence_default)
    return HealthProbeRequest(
        role=spec.role,
        service=spec.service,
        evidence_path=Path(evidence),
        budget=ProgressBudget(
            stale_seconds=_threshold(
                values,
                "--stale-seconds",
                "SERVICE_HEALTH_STALE_SECONDS",
                spec.budget.stale_seconds,
            ),
            grace_seconds=_threshold(
                values,
                "--grace-seconds",
                "SERVICE_HEALTH_GRACE_SECONDS",
                spec.budget.grace_seconds,
            ),
            extended_seconds=_threshold(
                values,
                "--extended-seconds",
                "SERVICE_HEALTH_EXTENDED_SECONDS",
                spec.budget.extended_seconds,
            ),
        ),
        probe_url=_probe_url(spec),
        missing_reason=spec.missing_reason,
    )


def _cli_values(argv: Sequence[str]) -> dict[str, str]:
    """Return the ``--flag value`` pairs carried by one invocation.

    Raises:
        UsageError: If a token is not a ``--flag value`` pair.
    """
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if not token.startswith("--") or index + 1 >= len(argv):
            message = f"unsupported argument {sanitize_fragment(token)}; expected --role and optional overrides"
            raise UsageError(message)
        values[token] = argv[index + 1]
        index += 2
    return values


def _threshold(values: Mapping[str, str], option: str, environment: str, default: int) -> int:
    """Return the resolved positive threshold for one option.

    Args:
        values: Parsed ``--flag value`` pairs.
        option: CLI option that may override the role default.
        environment: Environment variable that may override the role default.
        default: Role default used when neither override is present.

    Returns:
        The resolved positive integer threshold.

    Raises:
        ValueError: If an override is not a positive decimal integer.
    """
    raw = values.get(option)
    if raw is None:
        return positive_env_integer(environment, default)
    if not raw.isdigit() or int(raw) <= 0:
        message = f"positive_integer_required={option}"
        raise ValueError(message)
    return int(raw)


def _probe_url(spec: RoleSpec) -> str:
    """Return the container-local liveness endpoint, empty when unused.

    Args:
        spec: Deployment specification being probed.

    Returns:
        The registry liveness URL, or an empty string for worker roles.
    """
    if spec.role != _REGISTRY_ROLE:
        return ""
    port = positive_env_integer("E2E_REGISTRY_PORT", _DEFAULT_REGISTRY_PORT)
    return f"http://127.0.0.1:{port}/health"
