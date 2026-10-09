# Copyright (c) 2026 PitchAI. All rights reserved.
"""Isolated Chromium option construction without a process or OS observation."""

from __future__ import annotations

import unittest

from .browser_launch import chromium_arguments, launch_options
from .dft_test_support import require


class BrowserLaunchTests(unittest.TestCase):
    """Verify the exact launch flags and fresh caller-owned option bundles."""

    @staticmethod
    def test_original_memory_boundary_and_fresh_arguments() -> None:
        """Exactly 512MiB is sufficient; absent capacity takes the existing fallback."""
        for size, fallback in ((0, True), (536870911, True), (536870912, False), (536870913, False)):
            first, second = chromium_arguments(size), chromium_arguments(size)
            require(condition=first == second and first is not second, message="arguments reused or unstable")
            require(condition=("--disable-dev-shm-usage" in first) is fallback, message="capacity boundary changed")
            require(condition=first[0] == "--no-sandbox", message="argument order changed")
        require(condition=chromium_arguments(0)[1] == "--disable-dev-shm-usage", message="OS fallback lost")

    @staticmethod
    def test_optional_executable_is_omitted_or_preserved() -> None:
        """Absent/empty executable is omitted and supplied executable is unchanged."""
        for executable in (None, "", "/synthetic/chromium"):
            options = launch_options(0, executable)
            require(condition=options["headless"] is True, message="headless setting changed")
            if executable:
                require(condition=options.get("executable_path") == executable, message="executable changed")
            else:
                require(condition="executable_path" not in options, message="omission replaced with null")

    @staticmethod
    def test_caller_mutation_does_not_change_future_launches() -> None:
        """Mutable per-launch arguments must never become shared process state."""
        first = launch_options(0, "/synthetic/chromium")
        first["args"].clear()
        first["headless"] = False
        second = launch_options(0, "/synthetic/chromium")
        require(condition=bool(second["args"]) and second["headless"], message="launch configuration leaked")
