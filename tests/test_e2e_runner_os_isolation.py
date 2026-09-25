# Copyright (c) 2026 PitchAI. All rights reserved.
"""Kernel-level probes for submitted-code identity and process isolation."""

from __future__ import annotations

import asyncio
import stat
import uuid
from typing import TYPE_CHECKING

import pytest

from e2e_registry.testing import require_test_condition
from e2e_runner.code_execution import build_sandbox_environment
from e2e_runner.isolation import (
    acquire_submission_identity,
    release_submission_identity,
    seal_submission_filesystem,
    terminate_identity_processes,
)
from e2e_runner.redaction import sensitive_output_variants
from tests.e2e_runner_isolation_support import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    SYSTEM_PYTHON,
    cleanup_prepared,
    create_root_probe_file,
    launch_child,
    prepare_identity,
    traversable_root,
)
from tests.e2e_runner_os_assertions import (
    verify_descendant_termination,
    verify_identity_isolation,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_OUTPUT_SCRIPT = """
import os
import sys

with open(os.path.join(os.environ["ARTIFACTS_DIR"], "result.txt"), "w", encoding="utf-8") as handle:
    handle.write("ok")
print(os.environ["AFASASK_DEMO_USERNAME"])
print(sys.argv[1], file=sys.stderr)
"""


@pytest.fixture(name="os_probe_root")
def provide_os_probe_root() -> Iterator[Path]:
    """Provide a world-traversable root for real dropped-UID probes.

    Yields:
        A temporary root whose parent path can be traversed by sandbox UIDs.
    """
    with traversable_root("pitchai-e2e-isolation-") as root:
        yield root


@pytest.mark.asyncio
async def test_real_children_use_distinct_non_root_pools_and_cannot_read_parent(
    monkeypatch: pytest.MonkeyPatch,
    os_probe_root: Path,
) -> None:
    """Dropped-UID children must not inherit or read supervisor-only data."""
    parent_secret = uuid.uuid4().hex
    monkeypatch.setenv("PARENT_TRUST_SECRET", parent_secret)
    monkeypatch.setenv("AFASASK_DEMO_USERNAME", parent_secret)
    root_probe = os_probe_root / "root-only.txt"
    await asyncio.to_thread(create_root_probe_file, root_probe)
    trusted = await prepare_identity(os_probe_root / "jobs", trusted=True)
    untrusted = await prepare_identity(os_probe_root / "jobs", trusted=False)
    second_untrusted = acquire_submission_identity(
        artifacts_directory=os_probe_root / "second-untrusted",
        trusted_credentials={},
    )
    try:
        await verify_identity_isolation(
            trusted,
            untrusted,
            second_untrusted,
            root_probe=root_probe,
        )
    finally:
        release_submission_identity(second_untrusted)
        await asyncio.gather(cleanup_prepared(trusted), cleanup_prepared(untrusted))


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "timed_out"), [("success", False), ("timeout", True)])
async def test_escaped_descendants_are_killed_after_parent_exit(
    os_probe_root: Path,
    mode: str,
    *,
    timed_out: bool,
) -> None:
    """UID cleanup must kill setsid descendants after success and timeout."""
    prepared = await prepare_identity(os_probe_root / mode, trusted=False)
    environment = build_sandbox_environment(
        base_url="https://target.invalid",
        artifacts_dir=prepared.artifacts_directory,
        identity=prepared.identity,
    )
    try:
        await verify_descendant_termination(
            prepared,
            environment,
            mode=mode,
            timed_out=timed_out,
        )
    finally:
        await cleanup_prepared(prepared)


@pytest.mark.asyncio
async def test_output_is_redacted_and_tree_is_sealed_before_uid_reuse(os_probe_root: Path) -> None:
    """Credential output must be scrubbed and completed paths reclaimed by root."""
    username = uuid.uuid4().hex
    password = uuid.uuid4().hex
    credentials = {"AFASASK_DEMO_USERNAME": username, "AFASASK_DEMO_PASSWORD": password}
    prepared = await prepare_identity(os_probe_root / "sealed", trusted=True)
    environment = build_sandbox_environment(
        base_url="https://target.invalid",
        artifacts_dir=prepared.artifacts_directory,
        identity=prepared.identity,
        trusted_credentials=credentials,
    )
    basic_token = sensitive_output_variants(credentials)[-1]
    command = [
        SYSTEM_PYTHON,
        "-c",
        _OUTPUT_SCRIPT,
        basic_token,
    ]
    capture = await launch_child(
        prepared,
        command,
        environment,
        deadline_seconds=3.0,
        sensitive_values=sensitive_output_variants(credentials),
    )
    captured_text = (capture.stdout + capture.stderr).decode("utf-8")
    for value in sensitive_output_variants(credentials):
        require_test_condition(condition=value not in captured_text, message="captured output must redact credentials")
    await terminate_identity_processes(prepared.identity)
    await asyncio.to_thread(seal_submission_filesystem, prepared.artifacts_directory)
    directory_stat = await asyncio.to_thread(prepared.artifacts_directory.stat)
    result_stat = await asyncio.to_thread((prepared.artifacts_directory / "result.txt").stat)
    require_test_condition(
        condition=directory_stat.st_uid == 0 and stat.S_IMODE(directory_stat.st_mode) == PRIVATE_DIRECTORY_MODE,
        message="the completed job tree must be root-owned mode 0700 before UID release",
    )
    require_test_condition(
        condition=result_stat.st_uid == 0 and stat.S_IMODE(result_stat.st_mode) == PRIVATE_FILE_MODE,
        message="submission-created files must be root-owned mode 0600 before UID release",
    )
    original_uid = prepared.identity.uid
    release_submission_identity(prepared.identity)
    reused = acquire_submission_identity(
        artifacts_directory=os_probe_root / "reused",
        trusted_credentials={"AFASASK_DEMO_USERNAME": "approved"},
    )
    require_test_condition(condition=reused.uid == original_uid, message="only a sealed tree may precede UID reuse")
    release_submission_identity(reused)
