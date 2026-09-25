# Copyright (c) 2026 PitchAI. All rights reserved.
"""Behavior assertions for real submitted-code operating-system isolation."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, cast

from e2e_registry.testing import require_test_condition
from e2e_runner.code_execution import build_sandbox_environment
from e2e_runner.isolation import terminate_identity_processes
from tests.e2e_runner_isolation_support import (
    DESCENDANT_SCRIPT,
    PROBE_SCRIPT,
    SYSTEM_PYTHON,
    TRUSTED_UID_MAXIMUM,
    TRUSTED_UID_MINIMUM,
    UNTRUSTED_UID_MAXIMUM,
    UNTRUSTED_UID_MINIMUM,
    launch_child,
    process_is_live,
)

if TYPE_CHECKING:
    from pathlib import Path

    from e2e_runner.isolation import SandboxIdentity
    from tests.e2e_runner_isolation_support import PreparedIdentity

_EXPECTED_ACTIVE_UID_COUNT = 3


async def verify_identity_isolation(
    trusted: PreparedIdentity,
    untrusted: PreparedIdentity,
    second_untrusted: SandboxIdentity,
    *,
    root_probe: Path,
) -> None:
    """Verify distinct pools, dropped identities, and parent-data isolation."""
    identities = {trusted.identity.uid, untrusted.identity.uid, second_untrusted.uid}
    require_test_condition(
        condition=len(identities) == _EXPECTED_ACTIVE_UID_COUNT,
        message="active jobs must lease distinct UIDs",
    )
    require_test_condition(
        condition=TRUSTED_UID_MINIMUM <= trusted.identity.uid < TRUSTED_UID_MAXIMUM,
        message="trusted jobs must use the dedicated trusted UID pool",
    )
    require_test_condition(
        condition=UNTRUSTED_UID_MINIMUM <= untrusted.identity.uid < UNTRUSTED_UID_MAXIMUM,
        message="untrusted jobs must use the dedicated untrusted UID pool",
    )
    command = [SYSTEM_PYTHON, "-c", PROBE_SCRIPT, str(os.getpid()), str(root_probe)]
    trusted_environment = build_sandbox_environment(
        base_url="https://trusted.invalid",
        artifacts_dir=trusted.artifacts_directory,
        identity=trusted.identity,
        trusted_credentials={"AFASASK_DEMO_USERNAME": "approved"},
    )
    untrusted_environment = build_sandbox_environment(
        base_url="https://untrusted.invalid",
        artifacts_dir=untrusted.artifacts_directory,
        identity=untrusted.identity,
    )
    captures = await asyncio.gather(
        launch_child(trusted, command, trusted_environment, deadline_seconds=3.0),
        launch_child(untrusted, command, untrusted_environment, deadline_seconds=3.0),
    )
    records = [cast("dict[str, object]", json.loads(item.stdout)) for item in captures]
    for record, identity in zip(records, (trusted.identity, untrusted.identity), strict=True):
        require_test_condition(
            condition=int(str(record["euid"])) == identity.uid and identity.uid != 0,
            message="submitted code must execute under its leased non-root UID",
        )
        require_test_condition(
            condition=record["parent_environment_readable"] is False,
            message="submitted code must not read the root supervisor environment",
        )
        require_test_condition(
            condition=record["root_file_readable"] is False,
            message="submitted code must not read root-only files",
        )
        require_test_condition(
            condition=record["parent_secret"] is None,
            message="submitted code must not inherit arbitrary parent secrets",
        )
    require_test_condition(
        condition=records[1]["afas_username"] is None,
        message="untrusted code must not inherit trusted canary credentials",
    )


async def verify_descendant_termination(
    prepared: PreparedIdentity,
    environment: dict[str, str],
    *,
    mode: str,
    timed_out: bool,
) -> None:
    """Verify UID cleanup kills setsid descendants after either parent outcome."""
    capture = await launch_child(
        prepared,
        [SYSTEM_PYTHON, "-c", DESCENDANT_SCRIPT, mode],
        environment,
        deadline_seconds=0.5 if timed_out else 3.0,
    )
    child_pid_text = await asyncio.to_thread(
        (prepared.artifacts_directory / "child.pid").read_text,
        encoding="utf-8",
    )
    child_pid = int(child_pid_text)
    require_test_condition(
        condition=capture.timed_out is timed_out,
        message="the parent process must retain its declared deadline state",
    )
    await terminate_identity_processes(prepared.identity)
    child_is_live = await asyncio.to_thread(process_is_live, child_pid)
    require_test_condition(
        condition=not child_is_live,
        message="escaped UID-owned descendants must be dead",
    )
