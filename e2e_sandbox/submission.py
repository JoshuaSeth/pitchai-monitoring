# Copyright (c) 2026 PitchAI. All rights reserved.
"""Dynamic module boundary for submitted Playwright Python tests."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from types import ModuleType

    from playwright.async_api import Page

    type PageEntry = Callable[[Page, str, str], object]
    type MainEntry = Callable[[str, str], object]


class InvalidSubmissionError(RuntimeError):
    """Raised when a submitted module does not expose a supported entry point."""


def load_submission(path: Path) -> ModuleType:
    """Load one staged submitted module from its verified path.

    Returns:
        The executed submitted module.

    Raises:
        InvalidSubmissionError: If Python cannot construct a module loader.
    """
    resolved_path = path.resolve(strict=True)
    module_digest = hashlib.sha256(str(resolved_path).encode()).hexdigest()[:16]
    module_name = f"submitted_e2e_{module_digest}"
    specification = importlib.util.spec_from_file_location(module_name, resolved_path)
    if specification is None or specification.loader is None:
        message = "could_not_load_test_module"
        raise InvalidSubmissionError(message)
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


async def invoke_submission(
    *,
    module: ModuleType,
    page: Page,
    base_url: str,
    artifacts_dir: Path,
) -> None:
    """Invoke the supported entry point exposed by a submitted module.

    Raises:
        InvalidSubmissionError: If neither ``run`` nor ``main`` is callable.
    """
    run_candidate = cast("object", getattr(module, "run", None))
    main_candidate = cast("object", getattr(module, "main", None))
    result: object
    if callable(run_candidate):
        run_entry = cast("PageEntry", run_candidate)
        result = run_entry(page, base_url, str(artifacts_dir))
    elif callable(main_candidate):
        main_entry = cast("MainEntry", main_candidate)
        result = main_entry(base_url, str(artifacts_dir))
    else:
        message = "test_file_must_define_run_or_main"
        raise InvalidSubmissionError(message)
    if inspect.isawaitable(result):
        _ = await cast("Awaitable[object]", result)
