# Copyright (c) 2026 PitchAI. All rights reserved.
"""Shared real-process setup for submitted-code isolation tests."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from e2e_runner.isolation import (
    acquire_submission_identity,
    prepare_submission_filesystem,
    release_submission_identity,
    seal_submission_filesystem,
    terminate_identity_processes,
)
from e2e_runner.process_gateway import collect_process_output, launch_isolated_process

if TYPE_CHECKING:
    from collections.abc import Generator

    from e2e_runner.isolation import SandboxIdentity
    from e2e_runner.process_gateway import ProcessCapture

TRUSTED_UID_MINIMUM = 55_000
TRUSTED_UID_MAXIMUM = 56_000
UNTRUSTED_UID_MINIMUM = 60_000
UNTRUSTED_UID_MAXIMUM = 65_000
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
TRAVERSABLE_DIRECTORY_MODE = 0o711
SYSTEM_PYTHON = "/usr/bin/python3"
READABLE_SCRIPT = """
import os
from pathlib import Path

def readable(path):
    try:
        Path(path).read_bytes()
    except OSError:
        return False
    return True
"""
PROBE_SCRIPT = READABLE_SCRIPT + """
import json
import sys

print(json.dumps({
    "euid": os.geteuid(),
    "parent_environment_readable": readable(f"/proc/{sys.argv[1]}/environ"),
    "root_file_readable": readable(sys.argv[2]),
    "parent_secret": os.getenv("PARENT_TRUST_SECRET"),
    "afas_username": os.getenv("AFASASK_DEMO_USERNAME"),
}))
"""
DESCENDANT_SCRIPT = """
import os
from pathlib import Path
import subprocess
import sys
import time

child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(120)"],
    start_new_session=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
Path(os.environ["ARTIFACTS_DIR"]).joinpath("child.pid").write_text(str(child.pid), encoding="utf-8")
print(child.pid, flush=True)
if sys.argv[1] == "timeout":
    time.sleep(120)
"""


@dataclass(frozen=True)
class PreparedIdentity:
    """Leased sandbox identity with its prepared private paths."""

    identity: SandboxIdentity
    artifacts_directory: Path
    staged_source: Path


@contextmanager
def traversable_root(prefix: str) -> Generator[Path]:
    """Yield and remove a traversal-only root below ``/tmp``.

    Yields:
        The temporary traversal-only root.
    """
    root = Path(tempfile.mkdtemp(prefix=prefix, dir="/tmp"))
    root.chmod(TRAVERSABLE_DIRECTORY_MODE)
    try:
        yield root
    finally:
        shutil.rmtree(root)


async def prepare_identity(root: Path, *, trusted: bool) -> PreparedIdentity:
    """Prepare a private job tree for one leased UID.

    Returns:
        The leased identity and prepared filesystem paths.
    """
    artifacts_directory = root / uuid.uuid4().hex
    staged_source = artifacts_directory / "verified_source.py"
    await asyncio.to_thread(artifacts_directory.mkdir, parents=True, mode=PRIVATE_DIRECTORY_MODE)
    _ = await asyncio.to_thread(staged_source.write_text, "# staged source\n", encoding="utf-8")
    await asyncio.to_thread(staged_source.chmod, PRIVATE_FILE_MODE)
    credentials = {"AFASASK_DEMO_USERNAME": "approved"} if trusted else {}
    identity = acquire_submission_identity(
        artifacts_directory=artifacts_directory,
        trusted_credentials=credentials,
    )
    await asyncio.to_thread(
        prepare_submission_filesystem,
        artifacts_directory=artifacts_directory,
        staged_source=staged_source,
        identity=identity,
    )
    return PreparedIdentity(identity, artifacts_directory, staged_source)


async def cleanup_prepared(prepared: PreparedIdentity) -> None:
    """Kill UID-owned processes, seal paths, and release the lease."""
    await terminate_identity_processes(prepared.identity)
    await asyncio.to_thread(seal_submission_filesystem, prepared.artifacts_directory)
    release_submission_identity(prepared.identity)


async def launch_child(
    prepared: PreparedIdentity,
    command: list[str],
    environment: dict[str, str],
    *,
    deadline_seconds: float,
    sensitive_values: tuple[str, ...] = (),
) -> ProcessCapture:
    """Launch and collect one real dropped-identity subprocess.

    Returns:
        The bounded and redacted process capture.
    """
    process = await launch_isolated_process(
        command,
        environment=environment,
        identity=prepared.identity,
    )
    return await collect_process_output(
        process,
        deadline_seconds=deadline_seconds,
        timeout_cleanup=partial(terminate_identity_processes, prepared.identity),
        sensitive_values=sensitive_values,
    )


def create_root_probe_file(path: Path) -> None:
    """Create one root-owned mode-0600 access probe."""
    path.write_text("root-only", encoding="utf-8")
    path.chmod(PRIVATE_FILE_MODE)
    os.chown(path, 0, 0)


def process_is_live(pid: int) -> bool:
    """Return whether a procfs process is still executable rather than a zombie."""
    stat_path = Path("/proc") / str(pid) / "stat"
    if not stat_path.exists():
        return False
    process_stat = stat_path.read_text(encoding="utf-8")
    state = process_stat.rsplit(")", maxsplit=1)[1].strip().split(maxsplit=1)[0]
    return state not in {"X", "Z"}
