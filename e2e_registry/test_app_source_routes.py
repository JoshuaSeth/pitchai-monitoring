# Copyright (c) 2026 PitchAI. All rights reserved.
"""Real multipart/ASGI and private temporary source-file compatibility contracts."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

from domain_checks.dft_test_support import require

from . import auth
from . import db as dbm
from .app import create_app
from .asgi_test_support import multipart, request
from .settings import RegistrySettings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .dashboard_records import Record

_TENANT = dbm.AuthedTenant("upload-owner", "fixture-key")
_HEADERS = {"authorization": "Bearer fixture-key", "cookie": "e2e_token_hash=fixture-cookie"}
_BASE = {"base_url": "https://fixture.invalid"}
_DEFINITION = b'{"steps":[{"type":"goto"}]}'
_INTERVAL = 120


class SourceRoutesTests(unittest.IsolatedAsyncioTestCase):
    """Use real temporary source bytes, substituted DB operations and no lifespan."""

    directory: str

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult | None:
        """Keep the fixture directory alive for the complete unittest lifecycle.

        Returns:
            The native unittest result after all cleanup has finished.
        """
        with tempfile.TemporaryDirectory(prefix="registry-source-contract-") as directory:
            self.directory = directory
            return super().run(result)

    def setUp(self) -> None:
        """Allocate this case's private source root and authenticate only its fixture tenant."""
        self.settings: RegistrySettings = RegistrySettings(
            tests_dir=self.directory, alerts_enabled=False, dispatch_enabled=False, strict_base_url_policy=False,
        )
        self.application: FastAPI = create_app(self.settings)
        self.enterContext(patch.object(auth, "get_api_key_by_hash", return_value=_TENANT))
        self.enterContext(patch.object(dbm, "get_api_key_by_hash", return_value=_TENANT))
        self.enterContext(patch.object(dbm, "_connect", side_effect=AssertionError("real database forbidden")))

    async def test_stepflow_multipart_validation_and_default_arguments(self) -> None:
        """StepFlow validation still precedes insertion and code files are not created."""
        with patch.object(dbm, "insert_test", return_value={"id": "created"}) as insertion:
            for content in (b"{}", _DEFINITION):
                headers, body = multipart({**_BASE, "kind": "stepflow"}, "test.json", content)
                response = await request(self.application, "/api/v1/tests/upload", method="POST",
                                         headers={**headers, **_HEADERS}, body=body)
                expected = HTTPStatus.BAD_REQUEST if content == b"{}" else HTTPStatus.OK
                require(condition=response.status_code == expected, message="definition classification changed")
            require(condition=insertion.call_count == 1, message="invalid definition reached DB")
            values = cast("Record", insertion.call_args.kwargs)
            require(condition=values["tenant_id"] == _TENANT.tenant_id and values["test_kind"] == "stepflow" and
                    values["name"] == "test" and values["source_relpath"] is None and values["test_id"] is None and
                    values["definition"] == {"name": "test", "steps": [{"type": "goto"}]},
                    message="definition insertion fields changed")
            entries = await asyncio.to_thread(os.listdir, self.directory)
            require(condition=not entries, message="StepFlow API created a source file")

    async def test_code_upload_writes_exact_bytes_and_metadata(self) -> None:
        """Scheduling form values and stored digest describe the actual file before insertion."""
        content = b"# synthetic uploaded source\n"
        with patch.object(dbm, "insert_test", return_value={"id": "created"}) as insertion:
            headers, body = multipart({**_BASE, "kind": "playwright_python", "interval_seconds": "120",
                                       "notify_on_recovery": "yes", "dispatch_on_failure": "0"}, "fixture.py", content)
            response = await request(self.application, "/api/v1/tests/upload", method="POST",
                                     headers={**headers, **_HEADERS}, body=body)
            require(condition=response.json() == {"ok": True, "test": {"id": "created"}}, message="upload failed")
            values = cast("Record", insertion.call_args.kwargs)
            require(condition=values["source_sha256"] == hashlib.sha256(content).hexdigest() and
                    values["interval_seconds"] == _INTERVAL and values["notify_on_recovery"] is True and
                    values["dispatch_on_failure"] is False, message="multipart options/digest changed")
            require(condition=(Path(self.directory) / str(values["source_relpath"])).read_bytes() == content,
                    message="inserted reference does not match written bytes")

    async def test_replacement_keeps_write_cleanup_database_order(self) -> None:
        """A missing final DB update does not undo the already-written source or old-file cleanup."""
        old = Path(self.directory) / _TENANT.tenant_id / "test" / "old.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old fixture")
        test: Record = {"test_kind": "playwright_python", "source_relpath": str(old.relative_to(self.directory))}
        with (
            patch.object(dbm, "get_test", return_value=test),
            patch.object(dbm, "update_test_source", return_value=False),
        ):
            headers, body = multipart({}, "new.py", b"new fixture")
            response = await request(self.application, "/api/v1/tests/test/source", method="POST",
                                     headers={**headers, **_HEADERS}, body=body)
            require(condition=response.status_code == HTTPStatus.NOT_FOUND, message="failed final update changed")
            require(condition=not old.exists() and old.with_name("new.py").read_bytes() == b"new fixture",
                    message="write/old cleanup effects changed")

    async def test_cleanup_failure_keeps_database_update(self) -> None:
        """Existing best-effort cleanup failures do not cancel the new source metadata write."""
        old = Path(self.directory) / _TENANT.tenant_id / "test" / "old.py"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"old fixture")
        with (
            patch.object(dbm, "get_test", return_value={"test_kind": "playwright_python",
                         "source_relpath": str(old.relative_to(self.directory))}),
            patch.object(dbm, "update_test_source", return_value=True) as update,
            patch.object(Path, "unlink", side_effect=OSError("retained old file")),
        ):
            headers, body = multipart({}, "new.py", b"new")
            response = await request(self.application, "/api/v1/tests/test/source", method="POST",
                                     headers={**headers, **_HEADERS}, body=body)
            require(condition=response.json() == {"ok": True} and update.call_count == 1 and old.exists(),
                    message="cleanup failure changed DB continuation")

    async def test_ui_and_api_keep_distinct_write_failure_policy(self) -> None:
        """Ordinary write errors are UI redirects but remain exceptions at the source API."""
        headers, body = multipart({}, "test.py", b"fixture")
        with (
            patch.object(dbm, "get_test", return_value={"test_kind": "playwright_python"}),
            patch.object(Path, "write_bytes", side_effect=OSError("fixture write failed")),
            patch.object(dbm, "update_test_source") as update,
        ):
            response = await request(self.application, "/ui/tests/test/source", method="POST",
                                     headers={**headers, **_HEADERS}, body=body)
            require(condition=response.status_code == HTTPStatus.SEE_OTHER and
                    b"Write+failed" in dict(response.headers)[b"location"], message="UI write error changed")
            with pytest.raises(OSError, match="fixture write failed"):
                await request(self.application, "/api/v1/tests/test/source", method="POST",
                              headers={**headers, **_HEADERS}, body=body)
            require(condition=update.call_count == 0, message="write failure reached DB update")

    async def test_ui_creation_db_failure_and_cancellation_remain_distinct(self) -> None:
        """An ordinary DB error is rendered; cancellation remains an interrupted request."""
        headers, body = multipart(_BASE, "test.json", _DEFINITION)
        with patch.object(dbm, "insert_test", side_effect=RuntimeError("fixture db failed")):
            response = await request(self.application, "/ui/upload", method="POST",
                                     headers={**headers, **_HEADERS}, body=body)
            require(condition=response.status_code == HTTPStatus.OK and b"db_error: fixture db failed" in response.body,
                    message="UI creation DB error changed")
        with (
            patch.object(dbm, "insert_test", side_effect=asyncio.CancelledError("fixture cancellation")),
            pytest.raises(asyncio.CancelledError, match="fixture cancellation"),
        ):
            await request(self.application, "/ui/upload", method="POST", headers={**headers, **_HEADERS}, body=body)

    async def test_download_definition_and_source_confinement(self) -> None:
        """Download retains its definition materialization and refuses a resolved escape."""
        with patch.object(dbm, "get_test", return_value={"definition_json": ' {"fixture":true} '}) as lookup:
            response = await request(self.application, "/api/v1/tests/test/source", headers=_HEADERS)
            require(condition=response.json() == {"fixture": True}, message="definition download changed")
            path = Path(self.directory) / _TENANT.tenant_id / "test" / "definition.json"
            require(condition=path.read_text() == '{"fixture":true}', message="materialized definition changed")
            lookup.return_value = {"test_kind": "playwright_python", "source_relpath": "../outside.py"}
            response = await request(self.application, "/api/v1/tests/test/source", headers=_HEADERS)
            require(condition=response.status_code == HTTPStatus.BAD_REQUEST and
                    response.json()["detail"] == "invalid_path", message="source confinement weakened")
