# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression tests for submitted-code runner trust boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import TYPE_CHECKING

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner.code_execution import build_sandbox_environment
from e2e_runner.credentials import (
    trusted_code_test_environment,
)
from e2e_runner.isolation import acquire_submission_identity, release_submission_identity
from e2e_runner.jobs import execute_job
from e2e_runner.models import RunnerJob
from tests.e2e_runner_credentials_support import (
    build_runner_config,
    prepare_mutated_canary,
    prepare_trusted_canary,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_runner_rejects_claimed_source_hash_mismatch(tmp_path: Path) -> None:
    """A changed source file must fail before its submitted code can execute."""
    tests_directory = tmp_path / "tests"
    source_path = tests_directory / "tenant" / "test.py"
    await asyncio.to_thread(source_path.parent.mkdir, parents=True)
    _ = await asyncio.to_thread(
        source_path.write_text,
        "async def run(*args):\n    return None\n",
        encoding="utf-8",
    )
    claimed_digest = hashlib.sha256(b"different claimed bytes").hexdigest()
    config = build_runner_config(tmp_path, tests_directory=tests_directory)
    job = RunnerJob(
        run_id="run-id",
        test_id="test-id",
        tenant_id="tenant-id",
        test_name="untrusted-test",
        base_url="https://target.invalid",
        timeout_seconds=5.0,
        test_kind="playwright_python",
        definition={},
        source_relpath="tenant/test.py",
        source_filename="test.py",
        source_sha256=claimed_digest,
    )

    result = await execute_job(browser=None, config=config, job=job)

    require_test_condition(
        condition=result.status == "fail",
        message="a source digest mismatch must fail closed",
    )
    require_test_condition(
        condition=result.error_kind == "source_hash_mismatch",
        message="a source digest mismatch must retain its stable error kind",
    )
    staged_source = config.artifacts_dir / job.tenant_id / job.test_id / job.run_id / "verified_source.py"
    require_test_condition(
        condition=not await asyncio.to_thread(staged_source.exists),
        message="unverified source bytes must never reach the execution staging path",
    )


def test_sandbox_environment_excludes_runner_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Submitted code receives only its explicit environment contract."""
    sensitive_value = uuid.uuid4().hex
    monkeypatch.setenv("E2E_REGISTRY_RUNNER_TOKEN", sensitive_value)
    monkeypatch.setenv("DATABASE_URL", sensitive_value)
    monkeypatch.setenv("PUPPETEER_API_SECRET", sensitive_value)
    monkeypatch.setenv("PUPPETEER_EXECUTABLE_PATH", "/opt/chromium")
    monkeypatch.setenv("AFASASK_MONITOR_TOKEN", sensitive_value)
    monkeypatch.setenv("AFASASK_DEMO_USERNAME", sensitive_value)
    monkeypatch.setenv("AFASASK_DEMO_PASSWORD", sensitive_value)

    identity = acquire_submission_identity(
        artifacts_directory=tmp_path / "artifacts",
        trusted_credentials={},
    )
    environment = build_sandbox_environment(
        base_url="https://target.invalid",
        artifacts_dir=tmp_path / "artifacts",
        identity=identity,
    )
    release_submission_identity(identity)

    require_test_condition(
        condition="E2E_REGISTRY_RUNNER_TOKEN" not in environment,
        message="the registry runner token must not enter submitted-code processes",
    )
    require_test_condition(
        condition="DATABASE_URL" not in environment,
        message="host database credentials must not enter submitted-code processes",
    )
    require_test_condition(
        condition="PUPPETEER_API_SECRET" not in environment,
        message="arbitrary PUPPETEER-prefixed secrets must not bypass the allowlist",
    )
    require_test_condition(
        condition=environment.get("PUPPETEER_EXECUTABLE_PATH") == "/opt/chromium",
        message="the explicit browser executable setting should remain available",
    )
    require_test_condition(
        condition="AFASASK_MONITOR_TOKEN" not in environment,
        message="the domain-monitoring token must never reach submitted-code processes",
    )
    require_test_condition(
        condition="AFASASK_DEMO_USERNAME" not in environment and "AFASASK_DEMO_PASSWORD" not in environment,
        message="AFAS demo credentials require a verified canary identity before forwarding",
    )


@pytest.mark.asyncio
async def test_demo_credentials_require_exact_registered_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Only the exact registered AFAS demo source receives its credential pair."""
    fixture = await prepare_trusted_canary(tmp_path)
    username = uuid.uuid4().hex
    password = uuid.uuid4().hex
    monkeypatch.setenv("AFASASK_DEMO_USERNAME", username)
    monkeypatch.setenv("AFASASK_DEMO_PASSWORD", password)

    require_test_condition(
        condition=trusted_code_test_environment(
            config=fixture.config,
            job=fixture.job,
            verified_source=fixture.verified_source,
        )
        == {"AFASASK_DEMO_USERNAME": username, "AFASASK_DEMO_PASSWORD": password},
        message="the exact verified AFAS demo canary must receive its approved credential pair",
    )
    monkeypatch.delenv("AFASASK_DEMO_PASSWORD")
    require_test_condition(
        condition=not trusted_code_test_environment(
            config=fixture.config,
            job=fixture.job,
            verified_source=fixture.verified_source,
        ),
        message="an incomplete AFAS demo credential pair must never be partially forwarded",
    )
    monkeypatch.setenv("AFASASK_DEMO_PASSWORD", password)
    mutated_source, mutated_job = await prepare_mutated_canary(fixture, tmp_path)
    require_test_condition(
        condition=not trusted_code_test_environment(
            config=fixture.config,
            job=mutated_job,
            verified_source=mutated_source,
        ),
        message="a self-consistent but unreviewed tenant source replacement must not receive credentials",
    )
    javascript_job = fixture.job._replace(test_kind="puppeteer_js")
    require_test_condition(
        condition=not trusted_code_test_environment(
            config=fixture.config,
            job=javascript_job,
            verified_source=fixture.verified_source,
        ),
        message="the AFAS credential pair must only enter the trusted Python sandbox",
    )
