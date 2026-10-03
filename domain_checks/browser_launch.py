# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing Chromium launch arguments and shared-memory admission fallback."""

from __future__ import annotations

from typing import NotRequired, TypedDict

_SHARED_MEMORY_MIN_BYTES = 512 * 1024 * 1024


class ChromiumLaunchOptions(TypedDict):
    """The exact optional keyword bundle sent to the native Chromium launcher."""

    headless: bool
    args: list[str]
    executable_path: NotRequired[str]


def base_chromium_arguments() -> list[str]:
    """Return fresh common flags; each caller retains its shared-memory policy."""
    return [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=site-per-process",
    ]


def chromium_arguments(shared_memory_bytes: int) -> list[str]:
    """Return a fresh argument list, using disk-backed shared memory when small."""
    args = base_chromium_arguments()
    if shared_memory_bytes < _SHARED_MEMORY_MIN_BYTES:
        args.insert(1, "--disable-dev-shm-usage")
    return args


def launch_options(shared_memory_bytes: int, executable: str | None) -> ChromiumLaunchOptions:
    """Build launch options, preserving omission of an absent executable.

    Returns:
        Fresh arguments; native launch, retry and cleanup stay with the cycle.
    """
    options: ChromiumLaunchOptions = {"headless": True, "args": chromium_arguments(shared_memory_bytes)}
    if executable:
        options["executable_path"] = executable
    return options
