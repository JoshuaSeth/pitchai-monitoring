# Copyright (c) 2026 PitchAI. All rights reserved.
"""Environment configuration boundary for monitoring event delivery."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from domain_checks.event_bus_models import EventBusConfig

if TYPE_CHECKING:
    from collections.abc import Mapping

_ENVIRONMENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_DEPLOYMENT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_MIN_SECRET_LENGTH = 32
_MAX_TIMEOUT_SECONDS = 60


def load_event_bus_config(
    environ: Mapping[str, str] | None = None,
) -> EventBusConfig | None:
    """Load optional Events Bus settings and reject partial configuration.

    Returns:
        Validated settings, or ``None`` when delivery is not configured.

    Raises:
        RuntimeError: Events Bus settings are partial or invalid.
    """
    source = os.environ if environ is None else environ
    webhook_url = str(source.get("PITCHAI_MONITORING_EVENT_BUS_URL") or "").strip()
    secret = str(source.get("PITCHAI_MONITORING_EVENT_BUS_SECRET") or "").strip()
    if not webhook_url and not secret:
        return None
    if not webhook_url or not secret:
        message = "Both PITCHAI_MONITORING_EVENT_BUS_URL and secret are required"
        raise RuntimeError(message)
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        message = "PITCHAI_MONITORING_EVENT_BUS_URL must be an HTTPS URL without userinfo"
        raise RuntimeError(message)
    if len(secret) < _MIN_SECRET_LENGTH:
        message = "PITCHAI_MONITORING_EVENT_BUS_SECRET must contain at least 32 characters"
        raise RuntimeError(message)
    environment = str(
        source.get("PITCHAI_MONITORING_ENVIRONMENT") or "production",
    ).strip()
    instance = str(source.get("PITCHAI_MONITORING_INSTANCE") or "pitchai-main").strip()
    deployment_sha = str(source.get("PITCHAI_MONITORING_DEPLOYMENT_SHA") or "").strip() or None
    if not _ENVIRONMENT_PATTERN.fullmatch(environment):
        message = "PITCHAI_MONITORING_ENVIRONMENT is invalid"
        raise RuntimeError(message)
    if not _INSTANCE_PATTERN.fullmatch(instance):
        message = "PITCHAI_MONITORING_INSTANCE is invalid"
        raise RuntimeError(message)
    if deployment_sha and not _DEPLOYMENT_SHA_PATTERN.fullmatch(deployment_sha):
        message = "PITCHAI_MONITORING_DEPLOYMENT_SHA must be a lowercase 40-byte SHA"
        raise RuntimeError(message)
    timeout_seconds = float(
        source.get("PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS") or "10",
    )
    if not 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        message = "PITCHAI_MONITORING_EVENT_BUS_TIMEOUT_SECONDS must be between 1 and 60"
        raise RuntimeError(message)
    return EventBusConfig(
        webhook_url=webhook_url,
        secret=secret,
        environment=environment,
        instance=instance,
        deployment_sha=deployment_sha,
        timeout_seconds=timeout_seconds,
    )
