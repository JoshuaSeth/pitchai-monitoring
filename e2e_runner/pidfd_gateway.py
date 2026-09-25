# Copyright (c) 2026 PitchAI. All rights reserved.
"""Linux pidfd syscalls for Python builds that omit ``os.pidfd_open``."""

from __future__ import annotations

import ctypes
import os
import platform
from collections.abc import Callable
from typing import cast

_SUPPORTED_MACHINES = frozenset({"aarch64", "amd64", "x86_64"})
_PIDFD_SEND_SIGNAL_SYSCALL = 424
_PIDFD_OPEN_SYSCALL = 434


type _Syscall = Callable[..., int]


def _linux_syscall(number: int, *arguments: int) -> int:
    machine = platform.machine().lower()
    if machine not in _SUPPORTED_MACHINES:
        message = f"pidfd sandbox cleanup is unsupported on architecture: {machine}"
        raise RuntimeError(message)
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = cast("_Syscall", libc.syscall)
    result = syscall(number, *arguments)
    if result < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return result


class PidfdGateway:
    """Typed access to stable Linux process-handle syscalls."""

    @staticmethod
    def open(pid: int) -> int:
        """Open a close-on-exec descriptor bound to one exact process.

        Returns:
            A stable descriptor for the requested process.

        Raises:
            ValueError: If the numeric process ID is not positive.
        """
        if pid <= 0:
            message = "pidfd process ID must be positive"
            raise ValueError(message)
        return _linux_syscall(_PIDFD_OPEN_SYSCALL, pid, 0)

    @staticmethod
    def signal(descriptor: int, signal_number: int) -> None:
        """Signal the exact process referenced by a pidfd.

        Raises:
            ValueError: If the descriptor is negative.
        """
        if descriptor < 0:
            message = "pidfd descriptor must not be negative"
            raise ValueError(message)
        _ = _linux_syscall(
            _PIDFD_SEND_SIGNAL_SYSCALL,
            descriptor,
            signal_number,
            0,
            0,
        )


PIDFD_GATEWAY = PidfdGateway()
