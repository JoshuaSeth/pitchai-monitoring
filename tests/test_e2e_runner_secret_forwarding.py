from __future__ import annotations

import hashlib
from pathlib import Path

from e2e_runner import main


def _runner_config(tests_dir: Path) -> main.RunnerConfig:
    return main.RunnerConfig(
        registry_base_url="http://registry",
        runner_token="runner-token",
        artifacts_dir="/tmp/artifacts",
        tests_dir=str(tests_dir),
        poll_seconds=5,
        concurrency=1,
        trace_on_failure=False,
        code_exec_mode="local",
    )


def _invocation(
    *,
    test_file: Path,
    test_id: str,
    tenant_id: str,
    source_sha256: str,
) -> main._CodeTestInvocation:
    return main._CodeTestInvocation(
        kind="playwright_python",
        test_file=test_file,
        base_url=main._AFASASK_DEMO_BASE_URL,
        artifacts_dir=test_file.parent / "artifacts",
        timeout_seconds=45.0,
        trace_on_failure=False,
        test_id=test_id,
        tenant_id=tenant_id,
        test_name=main._AFASASK_DEMO_TEST_NAME,
        source_filename=test_file.name,
        source_sha256=source_sha256,
    )


def test_demo_credentials_are_forwarded_only_to_registered_canary(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AFASASK_DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("AFASASK_DEMO_PASSWORD", "demo-password")
    test_file = (
        tmp_path
        / main._AFASASK_DEMO_TENANT_ID
        / main._AFASASK_DEMO_TEST_ID
        / "afasask_demo_codex_fast_ok.py"
    )
    test_file.parent.mkdir(parents=True)
    test_file.write_text("async def run(*args): pass\n", encoding="utf-8")
    source_sha = hashlib.sha256(test_file.read_bytes()).hexdigest()

    forwarded = main._trusted_code_test_env(
        cfg=_runner_config(tmp_path),
        invocation=_invocation(
            test_file=test_file,
            test_id=main._AFASASK_DEMO_TEST_ID,
            tenant_id=main._AFASASK_DEMO_TENANT_ID,
            source_sha256=source_sha,
        ),
    )

    assert forwarded == {
        "AFASASK_DEMO_USERNAME": "demo-user",
        "AFASASK_DEMO_PASSWORD": "demo-password",
    }


def test_demo_credentials_are_not_forwarded_on_identity_or_source_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AFASASK_DEMO_USERNAME", "demo-user")
    monkeypatch.setenv("AFASASK_DEMO_PASSWORD", "demo-password")
    test_file = tmp_path / "tenant" / "untrusted" / "afasask_demo_codex_fast_ok.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("async def run(*args): pass\n", encoding="utf-8")

    forwarded = main._trusted_code_test_env(
        cfg=_runner_config(tmp_path),
        invocation=_invocation(
            test_file=test_file,
            test_id="untrusted",
            tenant_id="tenant",
            source_sha256=hashlib.sha256(test_file.read_bytes()).hexdigest(),
        ),
    )
    assert forwarded == {}

    trusted_path = (
        tmp_path
        / main._AFASASK_DEMO_TENANT_ID
        / main._AFASASK_DEMO_TEST_ID
        / test_file.name
    )
    trusted_path.parent.mkdir(parents=True)
    trusted_path.write_bytes(test_file.read_bytes())
    mismatched_source = main._trusted_code_test_env(
        cfg=_runner_config(tmp_path),
        invocation=_invocation(
            test_file=trusted_path,
            test_id=main._AFASASK_DEMO_TEST_ID,
            tenant_id=main._AFASASK_DEMO_TENANT_ID,
            source_sha256="0" * 64,
        ),
    )
    assert mismatched_source == {}
