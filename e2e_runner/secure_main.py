# Copyright (c) 2026 PitchAI. All rights reserved.
"""Run the established E2E worker with the trusted canary policy installed."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

from .trusted_afasask_canaries import (
    CodeTestIdentity,
    trusted_canary_environment,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .trusted_afasask_canaries import RunnerTestDirectory


class _RunnerModule(NamedTuple):
    main: object


_RUNNER = cast("_RunnerModule", cast("object", import_module("e2e_runner.main")))
_RUNNER_MAIN = cast("Callable[[], None]", _RUNNER.main)
_RUNNER_NAMESPACE = cast("dict[str, object]", vars(cast("object", _RUNNER)))


def _trusted_environment(
    *,
    cfg: RunnerTestDirectory,
    invocation: CodeTestIdentity,
) -> dict[str, str]:
    identity = CodeTestIdentity(
        test_id=invocation.test_id,
        tenant_id=invocation.tenant_id,
        test_name=invocation.test_name,
        base_url=invocation.base_url,
        test_file=invocation.test_file,
        source_filename=invocation.source_filename,
        source_sha256=invocation.source_sha256,
    )
    return trusted_canary_environment(
        tests_root=Path(cfg.tests_dir),
        identity=identity,
        environment=os.environ,
    )


def main() -> None:
    """Install the exact-source credential boundary and run the worker."""
    _RUNNER_NAMESPACE["_trusted_code_test_env"] = _trusted_environment
    _RUNNER_MAIN()


if __name__ == "__main__":
    main()
