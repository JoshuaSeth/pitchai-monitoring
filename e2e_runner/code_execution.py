# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated subprocess execution for submitted code tests."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, cast

from e2e_runner.execution_command import execution_command
from e2e_runner.isolation import (
    acquire_submission_identity,
    prepare_submission_filesystem,
    release_submission_identity,
    seal_submission_filesystem,
    terminate_identity_processes,
)
from e2e_runner.process_gateway import collect_process_output, launch_isolated_process
from e2e_runner.redaction import sensitive_output_variants

if TYPE_CHECKING:
    from pathlib import Path

    from e2e_registry.models import JsonObject, UntrustedJsonValue
    from e2e_runner.execution_models import CodeExecutionRequest
    from e2e_runner.isolation import SandboxIdentity
    from e2e_runner.process_gateway import ProcessCapture

_RESULT_LINE_PATTERN = re.compile(r"^E2E_RESULT_JSON=(\{.*\})\s*$")
_INHERITED_ENVIRONMENT_KEYS = frozenset(
    {
        "CHROMIUM_PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NODE_PATH",
        "PATH",
        "PUPPETEER_EXECUTABLE_PATH",
        "PUPPETEER_SKIP_DOWNLOAD",
        "TZ",
    },
)
_TRUSTED_CREDENTIAL_KEYS = frozenset({"AFASASK_DEMO_USERNAME", "AFASASK_DEMO_PASSWORD"})


@dataclass(frozen=True)
class ParsedCodeResult:
    """Structured sandbox output or its stable protocol failure."""

    result: JsonObject | None
    error_kind: str | None
    error_message: str | None


@dataclass(frozen=True)
class CodeExecutionOutput:
    """Captured output and structured result from a sandbox process."""

    parsed_result: ParsedCodeResult
    combined_output: str


def build_sandbox_environment(
    *,
    base_url: str,
    artifacts_dir: Path,
    identity: SandboxIdentity,
    trusted_credentials: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the exact environment contract for approved submitted canaries.

    Returns:
        A subprocess environment that excludes registry and host secrets.

    Raises:
        ValueError: If a caller attempts to forward an unapproved credential key.
    """
    environment: dict[str, str] = {}
    for key in _INHERITED_ENVIRONMENT_KEYS:
        value = os.getenv(key)
        if value is not None:
            environment[key] = value
    environment["HOME"] = str(identity.home_directory)
    environment["TMPDIR"] = str(identity.temporary_alias)
    environment["BASE_URL"] = base_url
    environment["ARTIFACTS_DIR"] = str(artifacts_dir)
    if trusted_credentials is not None:
        unsupported_keys = trusted_credentials.keys() - _TRUSTED_CREDENTIAL_KEYS
        if unsupported_keys:
            message = f"unsupported submitted-code credential keys: {sorted(unsupported_keys)}"
            raise ValueError(message)
        environment.update(trusted_credentials)
    return environment


def extract_result_json(text: str) -> ParsedCodeResult:
    """Extract and validate the last structured result from sandbox output.

    Returns:
        A parsed object or a distinct missing/malformed protocol failure.
    """
    encoded_result: str | None = None
    for line in text.splitlines():
        match = _RESULT_LINE_PATTERN.match(line.strip())
        if match is not None:
            encoded_result = match.group(1)
    if encoded_result is None:
        return ParsedCodeResult(
            result=None,
            error_kind="missing_result_json",
            error_message="runner output did not include E2E_RESULT_JSON",
        )

    try:
        decoded = cast("UntrustedJsonValue", json.loads(encoded_result))
    except json.JSONDecodeError:
        return ParsedCodeResult(
            result=None,
            error_kind="invalid_result_json",
            error_message="sandbox result JSON is malformed",
        )
    if not isinstance(decoded, dict):
        return ParsedCodeResult(
            result=None,
            error_kind="invalid_result_json",
            error_message="sandbox result JSON must be an object",
        )
    return ParsedCodeResult(result=decoded, error_kind=None, error_message=None)


def interpret_process_capture(capture: ProcessCapture) -> CodeExecutionOutput:
    """Map captured bytes and deadline state to the submitted-code contract.

    Returns:
        A normalized timeout or parsed sandbox protocol result.
    """
    stdout = capture.stdout.decode("utf-8", errors="replace")
    stderr = capture.stderr.decode("utf-8", errors="replace")
    combined_output = f"{stdout.strip()}\n{stderr.strip()}".strip()
    if capture.timed_out:
        return CodeExecutionOutput(
            parsed_result=ParsedCodeResult(
                result=None,
                error_kind="code_execution_timeout",
                error_message=f"submitted test exceeded {capture.deadline_seconds:.1f} seconds",
            ),
            combined_output=combined_output,
        )
    return CodeExecutionOutput(
        parsed_result=extract_result_json(f"{stdout}\n{stderr}"),
        combined_output=combined_output,
    )


async def run_code_local(*, request: CodeExecutionRequest) -> CodeExecutionOutput:
    """Execute staged source under a unique non-root OS identity.

    Returns:
        Captured process output with expected timeout/protocol failures normalized.
    """
    identity = acquire_submission_identity(
        artifacts_directory=request.artifacts_dir,
        trusted_credentials=request.trusted_credentials,
    )
    try:
        capture = await _execute_under_identity(request=request, identity=identity)
    finally:
        await _clean_submission(request=request, identity=identity)
    return interpret_process_capture(capture)


async def _execute_under_identity(
    *,
    request: CodeExecutionRequest,
    identity: SandboxIdentity,
) -> ProcessCapture:
    await asyncio.to_thread(
        prepare_submission_filesystem,
        artifacts_directory=request.artifacts_dir,
        staged_source=request.test_file,
        identity=identity,
    )
    environment = build_sandbox_environment(
        base_url=request.base_url,
        artifacts_dir=request.artifacts_dir,
        identity=identity,
        trusted_credentials=request.trusted_credentials,
    )
    process = await launch_isolated_process(
        execution_command(request=request),
        environment=environment,
        identity=identity,
    )
    deadline_seconds = max(5.0, request.timeout_seconds + 15.0)
    return await collect_process_output(
        process,
        deadline_seconds=deadline_seconds,
        timeout_cleanup=partial(terminate_identity_processes, identity),
        sensitive_values=sensitive_output_variants(request.trusted_credentials),
    )


async def _clean_submission(
    *,
    request: CodeExecutionRequest,
    identity: SandboxIdentity,
) -> None:
    termination_failure: Exception | None = None
    sealing_failure: Exception | None = None
    try:
        await terminate_identity_processes(identity)
    except (OSError, RuntimeError, ValueError, IndexError) as error:
        termination_failure = error
    try:
        await asyncio.to_thread(seal_submission_filesystem, request.artifacts_dir)
    except (OSError, RuntimeError, ValueError, IndexError) as error:
        sealing_failure = error
    if sealing_failure is not None:
        raise sealing_failure
    if termination_failure is not None:
        raise termination_failure
    release_submission_identity(identity)
