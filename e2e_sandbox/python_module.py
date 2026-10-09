# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing submitted-module loading and run/main callable selection."""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from pathlib import Path
    from types import ModuleType

    from playwright.async_api import Page

    from domain_checks.event_bus_delivery import JsonValue


type SubmittedOutcome = JsonValue | Coroutine[None, None, JsonValue]
type RunEntry = Callable[[Page, str, str], SubmittedOutcome]
type MainEntry = Callable[[str, str], SubmittedOutcome]
type EntryPoint = RunEntry | MainEntry


def load_module_from_path(path: Path) -> ModuleType:
    """Load the existing submitted file under its path-derived module name.

    Returns:
        The executed module, registered before its loader executes.

    Raises:
        RuntimeError: No source loader exists for the submitted path.
    """
    resolved = path.resolve()
    name = f"submitted_e2e_{abs(hash(str(resolved)))}"
    spec = importlib.util.spec_from_file_location(name, str(resolved))
    if spec is None or spec.loader is None:
        message = "could_not_load_test_module"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def pick_entry(module: ModuleType) -> EntryPoint:
    """Prefer callable run, then callable main, preserving the original error.

    Returns:
        The actual callable, without wrapping or changing argument dispatch.

    Raises:
        RuntimeError: Neither supported callable is defined.
    """
    run = cast("EntryPoint | None", getattr(module, "run", None))
    if callable(run):
        return run
    main = cast("EntryPoint | None", getattr(module, "main", None))
    if callable(main):
        return main
    message = "test_file_must_define_run_or_main"
    raise RuntimeError(message)
