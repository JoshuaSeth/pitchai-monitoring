# Copyright (c) 2026 PitchAI. All rights reserved.
"""Fail-closed credential policy for registered AFASAsk canaries."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

AFASASK_TENANT_ID = "7b9ba3e7-d4f1-40b7-9124-27216975d091"
AFASASK_DEMO_TEST_ID = "2a267abf-42a8-47dc-9ab3-549acdf7f129"
AFASASK_PRODUCTION_MEDIUM_TEST_ID = "b0fd66f6-88a9-46bb-971e-511df9bc1c76"
AFASASK_DEMO_SOURCE_SHA256 = "b1cfcdad808133c31f6ab4570b423e171558f6a76277ddf00be6fd807bb1debd"
AFASASK_PRODUCTION_MEDIUM_SOURCE_SHA256 = "191631fd9caa091a247e01ed92c8e56f14f763d23da48d394e7c79b05c41a64c"

_CREDENTIAL_KEYS = ("AFASASK_DEMO_USERNAME", "AFASASK_DEMO_PASSWORD")


@dataclass(frozen=True)
class CodeTestIdentity:
    """Materialized code-test identity evaluated by the trust policy."""

    test_id: str
    tenant_id: str
    test_name: str
    base_url: str
    test_file: Path
    source_filename: str | None
    source_sha256: str | None


@dataclass(frozen=True)
class RunnerTestDirectory:
    """Materialized test directory exposed by the established runner."""

    tests_dir: str


@dataclass(frozen=True)
class _TrustedCanary:
    test_id: str
    test_name: str
    base_url: str
    source_filename: str
    source_sha256: str


_TRUSTED_CANARIES = (
    _TrustedCanary(
        test_id=AFASASK_DEMO_TEST_ID,
        test_name="afasask_demo_codex_fast_ok",
        base_url="https://demo.afasask.pitchai.net",
        source_filename="afasask_demo_codex_fast_ok.py",
        source_sha256=AFASASK_DEMO_SOURCE_SHA256,
    ),
    _TrustedCanary(
        test_id=AFASASK_PRODUCTION_MEDIUM_TEST_ID,
        test_name="afasask_production_codex_medium_synthetic_ok",
        base_url="https://afasask.gzb.nl",
        source_filename="afasask_production_codex_medium_synthetic_ok.py",
        source_sha256=AFASASK_PRODUCTION_MEDIUM_SOURCE_SHA256,
    ),
)


def trusted_canary_environment(
    *,
    tests_root: Path,
    identity: CodeTestIdentity,
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Return credentials only for an exact registered source identity.

    Returns:
        Both AFASAsk synthetic credentials for a trusted canary, otherwise an
        empty mapping.
    """
    normalized_base_url = identity.base_url.rstrip("/")
    claimed_sha = (identity.source_sha256 or "").strip().lower()
    trusted = next(
        (
            canary
            for canary in _TRUSTED_CANARIES
            if canary.test_id == identity.test_id
            and canary.test_name == identity.test_name
            and canary.base_url == normalized_base_url
            and canary.source_filename == identity.source_filename
            and canary.source_sha256 == claimed_sha
        ),
        None,
    )
    if trusted is None or identity.tenant_id != AFASASK_TENANT_ID or not identity.test_file.is_file():
        return {}

    resolved_file = identity.test_file.resolve()
    expected_parent = tests_root.resolve() / identity.tenant_id / identity.test_id
    if resolved_file.parent != expected_parent or resolved_file.name != trusted.source_filename:
        return {}
    actual_sha = hashlib.sha256(resolved_file.read_bytes()).hexdigest()
    if actual_sha != trusted.source_sha256:
        return {}

    credentials: dict[str, str] = {}
    for key in _CREDENTIAL_KEYS:
        value = environment.get(key, "")
        if not value:
            return {}
        credentials[key] = value
    return credentials
