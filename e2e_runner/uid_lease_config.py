# Copyright (c) 2026 PitchAI. All rights reserved.
"""Configuration and root-owned directory policy for sandbox UID leases."""

from __future__ import annotations

import os
import stat
from pathlib import Path

LEASE_DIRECTORY_ENVIRONMENT = "E2E_SANDBOX_UID_LEASE_DIR"
_DIRECTORY_MODE = 0o700


class SandboxLeaseError(RuntimeError):
    """Raised when the runner cannot safely lease a sandbox UID."""


def require_declared_shared_lease_directory() -> Path:
    """Require a declared absolute lease path for the long-running service.

    Returns:
        The operator-declared directory that must be backed by a shared mount.

    Raises:
        SandboxLeaseError: If the service has no explicit absolute lease path.
    """
    configured = os.getenv(LEASE_DIRECTORY_ENVIRONMENT)
    if configured is None or not configured.strip():
        message = (
            f"{LEASE_DIRECTORY_ENVIRONMENT} must declare a shared mounted lease directory "
            "for runner service startup"
        )
        raise SandboxLeaseError(message)
    directory = Path(configured.strip())
    if not directory.is_absolute():
        message = f"{LEASE_DIRECTORY_ENVIRONMENT} must be an absolute path"
        raise SandboxLeaseError(message)
    return directory


def prepare_lease_directory() -> Path:
    """Create or validate the root-only UID lease directory.

    Returns:
        The validated root-owned mode-0700 directory.

    Raises:
        SandboxLeaseError: If the configured path is not a protected directory.
    """
    directory = require_declared_shared_lease_directory()
    directory.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
    path_stat = directory.lstat()
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or path_stat.st_uid != 0
        or stat.S_IMODE(path_stat.st_mode) != _DIRECTORY_MODE
    ):
        message = f"sandbox lease directory must be root-owned mode-0700: {directory}"
        raise SandboxLeaseError(message)
    return directory
