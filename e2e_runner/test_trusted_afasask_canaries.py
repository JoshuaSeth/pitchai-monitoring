# Copyright (c) 2026 PitchAI. All rights reserved.
"""Regression coverage for exact AFASAsk canary credential trust."""

from __future__ import annotations

from dataclasses import replace
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast

from .trusted_afasask_canaries import (
    AFASASK_PRODUCTION_MEDIUM_SOURCE_SHA256,
    AFASASK_PRODUCTION_MEDIUM_TEST_ID,
    AFASASK_TENANT_ID,
    CodeTestIdentity,
    trusted_canary_environment,
)

_SOURCE_FILENAME = "afasask_production_codex_medium_synthetic_ok.py"

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import NoReturn


class _PytestModule(NamedTuple):
    fail: Callable[[str], NoReturn]


_PYTEST = cast("_PytestModule", cast("object", import_module("pytest")))


def _materialized_identity(tmp_path: Path) -> tuple[Path, CodeTestIdentity]:
    source = Path(__file__).resolve().parents[1] / "e2e_tests" / _SOURCE_FILENAME
    test_file = tmp_path / AFASASK_TENANT_ID / AFASASK_PRODUCTION_MEDIUM_TEST_ID / _SOURCE_FILENAME
    test_file.parent.mkdir(parents=True)
    test_file.write_bytes(source.read_bytes())
    identity = CodeTestIdentity(
        test_id=AFASASK_PRODUCTION_MEDIUM_TEST_ID,
        tenant_id=AFASASK_TENANT_ID,
        test_name="afasask_production_codex_medium_synthetic_ok",
        base_url="https://afasask.gzb.nl",
        test_file=test_file,
        source_filename=_SOURCE_FILENAME,
        source_sha256=AFASASK_PRODUCTION_MEDIUM_SOURCE_SHA256,
    )
    return tmp_path, identity


def test_production_medium_canary_receives_credentials_for_exact_source(tmp_path: Path) -> None:
    """Allow only the deployed production canary identity and bytes."""
    tests_root, identity = _materialized_identity(tmp_path)
    environment = {
        "AFASASK_DEMO_USERNAME": "synthetic-user",
        "AFASASK_DEMO_PASSWORD": "synthetic-password",
    }
    trusted = trusted_canary_environment(
        tests_root=tests_root,
        identity=identity,
        environment=environment,
    )
    if trusted != environment:
        _PYTEST.fail(f"exact production canary was not trusted: {trusted}")


def test_production_medium_canary_rejects_identity_path_and_source_mismatch(tmp_path: Path) -> None:
    """Fail closed for every registration and materialization mismatch."""
    tests_root, identity = _materialized_identity(tmp_path)
    environment = {
        "AFASASK_DEMO_USERNAME": "synthetic-user",
        "AFASASK_DEMO_PASSWORD": "synthetic-password",
    }
    mismatches = (
        replace(identity, test_id="wrong-test"),
        replace(identity, tenant_id="wrong-tenant"),
        replace(identity, test_name="wrong-name"),
        replace(identity, base_url="https://demo.afasask.pitchai.net"),
        replace(identity, source_filename="wrong.py"),
        replace(identity, source_sha256="0" * 64),
        replace(identity, test_file=tmp_path / _SOURCE_FILENAME),
    )
    for mismatch in mismatches:
        trusted = trusted_canary_environment(
            tests_root=tests_root,
            identity=mismatch,
            environment=environment,
        )
        if trusted:
            _PYTEST.fail(f"mismatched canary received credentials: {mismatch}")

    identity.test_file.write_text("tampered", encoding="utf-8")
    trusted_tampered = trusted_canary_environment(
        tests_root=tests_root,
        identity=identity,
        environment=environment,
    )
    if trusted_tampered:
        _PYTEST.fail("tampered canary source received credentials")


def test_production_medium_canary_requires_both_credentials(tmp_path: Path) -> None:
    """Avoid partially authenticated jobs when one secret is absent."""
    tests_root, identity = _materialized_identity(tmp_path)
    trusted = trusted_canary_environment(
        tests_root=tests_root,
        identity=identity,
        environment={"AFASASK_DEMO_USERNAME": "synthetic-user"},
    )
    if trusted:
        _PYTEST.fail("incomplete credentials crossed the runner boundary")
