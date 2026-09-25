# Copyright (c) 2026 PitchAI. All rights reserved.
"""Reviewed-source fixture setup for runner credential-boundary tests."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from e2e_registry.testing import require_test_condition
from e2e_runner.credentials import (
    AFASASK_DEMO_APPROVED_SOURCE_SHA256,
    AFASASK_DEMO_BASE_URL,
    AFASASK_DEMO_SOURCE_FILENAME,
    AFASASK_DEMO_TENANT_ID,
    AFASASK_DEMO_TEST_ID,
    AFASASK_DEMO_TEST_NAME,
)
from e2e_runner.integrity import VerifiedSource, stage_verified_source
from e2e_runner.models import RunnerConfig, RunnerJob

_BUNDLED_AFAS_CANARY = Path(__file__).resolve().parents[1] / "e2e_tests" / AFASASK_DEMO_SOURCE_FILENAME


@dataclass(frozen=True)
class TrustedCanaryFixture:
    """Verified reviewed canary and its production-shaped runner inputs."""

    config: RunnerConfig
    job: RunnerJob
    verified_source: VerifiedSource
    source_path: Path
    approved_source_bytes: bytes


def build_runner_config(tmp_path: Path, *, tests_directory: Path) -> RunnerConfig:
    """Build the production-shaped configuration shared by trust probes.

    Returns:
        A runner configuration rooted entirely below the test directory.
    """
    artifacts_directory = tmp_path / "artifacts"
    runner_token = uuid.uuid4().hex
    return RunnerConfig(
        tests_dir=tests_directory,
        artifacts_dir=artifacts_directory,
        registry_base_url="http://registry.invalid",
        runner_token=runner_token,
        concurrency=1,
        poll_seconds=1.0,
        trace_on_failure=False,
    )


async def prepare_trusted_canary(tmp_path: Path) -> TrustedCanaryFixture:
    """Stage the bundled reviewed AFAS canary for a credential probe.

    Returns:
        The verified source, matching job, configuration, and source bytes.
    """
    tests_directory = tmp_path / "tests"
    source_path = (
        tests_directory
        / AFASASK_DEMO_TENANT_ID
        / AFASASK_DEMO_TEST_ID
        / AFASASK_DEMO_SOURCE_FILENAME
    )
    await asyncio.to_thread(source_path.parent.mkdir, parents=True)
    approved_source_bytes = await asyncio.to_thread(_BUNDLED_AFAS_CANARY.read_bytes)
    _ = await asyncio.to_thread(source_path.write_bytes, approved_source_bytes)
    source_digest = hashlib.sha256(approved_source_bytes).hexdigest()
    require_test_condition(
        condition=source_digest in AFASASK_DEMO_APPROVED_SOURCE_SHA256,
        message="the bundled AFAS canary must have a reviewed credential-authorized digest",
    )
    source_outcome = await stage_verified_source(
        tests_dir=tests_directory,
        source_relpath=str(source_path.relative_to(tests_directory)),
        expected_sha256=source_digest,
        staging_dir=tmp_path / "staging",
    )
    require_test_condition(
        condition=isinstance(source_outcome, VerifiedSource),
        message="the exact credential test source must pass integrity staging",
    )
    verified_source = cast("VerifiedSource", source_outcome)
    config = build_runner_config(tmp_path, tests_directory=tests_directory)
    job = RunnerJob(
        test_kind="playwright_python",
        source_filename=AFASASK_DEMO_SOURCE_FILENAME,
        source_relpath=str(source_path.relative_to(tests_directory)),
        source_sha256=source_digest,
        definition={},
        base_url=AFASASK_DEMO_BASE_URL,
        tenant_id=AFASASK_DEMO_TENANT_ID,
        test_id=AFASASK_DEMO_TEST_ID,
        test_name=AFASASK_DEMO_TEST_NAME,
        run_id="run-id",
        timeout_seconds=5.0,
    )
    return TrustedCanaryFixture(config, job, verified_source, source_path, approved_source_bytes)


async def prepare_mutated_canary(
    fixture: TrustedCanaryFixture,
    tmp_path: Path,
) -> tuple[VerifiedSource, RunnerJob]:
    """Stage a self-consistent but unreviewed replacement canary.

    Returns:
        The verified replacement source and matching mutated job.
    """
    mutated_bytes = fixture.approved_source_bytes + b"\n# tenant replacement\n"
    _ = await asyncio.to_thread(fixture.source_path.write_bytes, mutated_bytes)
    mutated_digest = hashlib.sha256(mutated_bytes).hexdigest()
    mutated_outcome = await stage_verified_source(
        tests_dir=fixture.config.tests_dir,
        source_relpath=str(fixture.source_path.relative_to(fixture.config.tests_dir)),
        expected_sha256=mutated_digest,
        staging_dir=tmp_path / "mutated-staging",
    )
    require_test_condition(
        condition=isinstance(mutated_outcome, VerifiedSource),
        message="the replacement probe must model a tenant-updated matching registry digest",
    )
    mutated_source = cast("VerifiedSource", mutated_outcome)
    return mutated_source, fixture.job._replace(source_sha256=mutated_digest)
