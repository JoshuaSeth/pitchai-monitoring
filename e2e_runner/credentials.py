# Copyright (c) 2026 PitchAI. All rights reserved.
"""Identity-gated credential forwarding for trusted submitted canaries."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e2e_runner.integrity import VerifiedSource
    from e2e_runner.models import RunnerConfig, RunnerJob

AFASASK_DEMO_TEST_ID = "2a267abf-42a8-47dc-9ab3-549acdf7f129"
AFASASK_DEMO_TENANT_ID = "7b9ba3e7-d4f1-40b7-9124-27216975d091"
AFASASK_DEMO_TEST_NAME = "afasask_demo_codex_fast_ok"
AFASASK_DEMO_SOURCE_FILENAME = "afasask_demo_codex_fast_ok.py"
AFASASK_DEMO_BASE_URL = "https://demo.afasask.pitchai.net"
AFASASK_DEMO_APPROVED_SOURCE_SHA256 = frozenset(
    {
        # Live production source persisted in /data/e2e-tests before this release.
        "b1cfcdad808133c31f6ab4570b423e171558f6a76277ddf00be6fd807bb1debd",
        # Reviewed typed fixture bundled with this release for controlled migration.
        "dd2d58547022379511dbfea9068bb0ef572b9c15ece76e3390f04a85c14e9bf2",
    },
)
_AFASASK_DEMO_CREDENTIAL_KEYS = ("AFASASK_DEMO_USERNAME", "AFASASK_DEMO_PASSWORD")


def trusted_code_test_environment(
    *,
    config: RunnerConfig,
    job: RunnerJob,
    verified_source: VerifiedSource,
) -> dict[str, str]:
    """Forward demo credentials only to the exact registered AFAS canary.

    Returns:
        The approved credential pair for the trusted source, otherwise an empty mapping.
    """
    trusted_identity = (
        job.test_kind == "playwright_python"
        and job.test_id == AFASASK_DEMO_TEST_ID
        and job.tenant_id == AFASASK_DEMO_TENANT_ID
        and job.test_name == AFASASK_DEMO_TEST_NAME
        and job.base_url.rstrip("/") == AFASASK_DEMO_BASE_URL
        and job.source_filename == AFASASK_DEMO_SOURCE_FILENAME
        and job.source_sha256 == verified_source.sha256
        and verified_source.sha256 in AFASASK_DEMO_APPROVED_SOURCE_SHA256
    )
    if not trusted_identity:
        return {}

    expected_parent = config.tests_dir.resolve() / job.tenant_id / job.test_id
    trusted_source_path = (
        verified_source.original_path.parent == expected_parent
        and verified_source.original_path.name == AFASASK_DEMO_SOURCE_FILENAME
    )
    if not trusted_source_path:
        return {}

    credentials: dict[str, str] = {}
    for key in _AFASASK_DEMO_CREDENTIAL_KEYS:
        value = os.getenv(key)
        if value:
            credentials[key] = value
    return credentials if len(credentials) == len(_AFASASK_DEMO_CREDENTIAL_KEYS) else {}
