# Copyright (c) 2026 PitchAI. All rights reserved.
"""Monitoring response-window, access and asynchronous route contracts."""

from __future__ import annotations

import asyncio
import unittest
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from domain_checks.dft_test_support import require

from . import db as dbm
from . import monitor_dashboard as md
from .app_access import RegistryAccess
from .app_context import RegistryContext
from .app_dashboard_window import filter_summary_window
from .app_monitoring_routes import install_monitoring_routes
from .asgi_test_support import request
from .dashboard_records import array_or_empty, object_or_empty
from .settings import RegistrySettings

if TYPE_CHECKING:
    from .dashboard_records import Record

_IDENTITY = {"x-fixture-identity": "fixture@pitchai.net"}
_SUMMARY = "/dashboard/api/v1/monitoring/summary"
_DISPATCH_LIMIT = 80
_RANGE_START = 12
_RANGE_END = 20


def _context() -> RegistryContext:
    application = FastAPI()
    application.state.settings = RegistrySettings(
        admin_token="", monitor_token="", dashboard_identity_header="x-fixture-identity",
        alerts_enabled=False, dispatch_enabled=False,
    )
    context = RegistryContext(application)
    install_monitoring_routes(context, RegistryAccess(context))
    return context


class MonitoringRouteTests(unittest.IsolatedAsyncioTestCase):
    """In-process HTTP only, without lifecycle, storage, browser or delivery."""

    @staticmethod
    def test_window_retains_inclusive_rows_and_undated_dispatch_identity() -> None:
        """Invalid events omit; invalid/undated dispatches retain the original row."""
        before: Record = {"ts": 9}
        first: Record = {"ts": "10"}
        last: Record = {"ts": 20}
        after: Record = {"ts": 21}
        invalid: Record = {"ts": "bad"}
        undated: Record = {}
        dispatch: Record = {"recent": [before, first, last, after, invalid, undated]}
        summary: Record = {"events": [before, first, last, after, invalid, undated], "dispatch": dispatch}
        filter_summary_window(summary, since_ts=10, until_ts=20)
        require(condition=summary["events"] == [first, last], message="event window changed")
        require(condition=dispatch["recent"] == [first, last, invalid, undated], message="undated policy changed")
        require(condition=summary["dispatch"] is dispatch, message="dispatch mapping replaced")
        require(condition=array_or_empty(summary["events"])[0] is first, message="response row copied")

    @staticmethod
    def test_non_list_and_non_mapping_shapes_keep_empty_response_fallback() -> None:
        """Fallback is limited to response filtering and cannot close incidents."""
        summary: Record = {"events": "invalid", "dispatch": [1]}
        filter_summary_window(summary, since_ts=0, until_ts=20)
        require(condition=summary == {"events": [], "dispatch": {"recent": []}}, message="shape fallback changed")
        summary = {"events": [1, None, {"ts": 10}], "dispatch": {"recent": [False, {"ts": 10}]}}
        filter_summary_window(summary, since_ts=0, until_ts=20)
        require(condition=summary["events"] == [{"ts": 10}], message="non-mapping event retained")

    @staticmethod
    def test_nonfinite_timestamp_comparisons_keep_original_response_policy() -> None:
        """NaN compares neither before nor after; infinity remains outside bounds."""
        unusual: Record = {"ts": float("nan")}
        summary: Record = {"events": [unusual, {"ts": float("inf")}], "dispatch": {"recent": []}}
        filter_summary_window(summary, since_ts=10, until_ts=20)
        rows = array_or_empty(summary["events"])
        require(condition=len(rows) == 1 and rows[0] is unusual, message="nonfinite comparison policy changed")

    @staticmethod
    async def test_summary_preserves_auth_cache_database_and_build_order() -> None:
        """Unauthorized requests do no work; authorized requests retain sequencing."""
        context = _context()
        trace: list[str] = []
        snapshot = md.MonitorData({}, {}, "fixture", "fixture", 20, None)

        async def load(received: RegistryContext) -> md.MonitorData:
            require(condition=received is context, message="application context changed")
            trace.append("cache")
            await asyncio.sleep(0)
            return snapshot

        def status(settings: RegistrySettings) -> Record:
            require(condition=settings is context.settings, message="settings replaced")
            trace.append("status")
            return {"tests": []}

        def dispatch(settings: RegistrySettings, *, limit: int) -> list[Record]:
            require(condition=settings is context.settings and limit == _DISPATCH_LIMIT,
                    message="dispatch arguments changed")
            trace.append("dispatch")
            return []

        with (
            patch.object(RegistryContext, "monitor_data", new=load),
            patch.object(dbm, "status_summary", side_effect=status),
            patch.object(dbm, "list_dispatch_runs", side_effect=dispatch),
            patch.object(md, "build_dashboard_summary", return_value={"events": [], "dispatch": {}}) as build,
        ):
            refused = await request(context.app, _SUMMARY)
            require(condition=refused.status_code == HTTPStatus.UNAUTHORIZED and not trace,
                    message="unauthorized request did work")
            response = await request(context.app, _SUMMARY, headers=_IDENTITY)
            require(condition=response.status_code == HTTPStatus.OK, message="authorized response failed")
            require(condition=trace == ["cache", "status", "dispatch"], message="observation order changed")
            require(condition=build.call_count == 1, message="summary construction count changed")

    @staticmethod
    async def test_failed_or_cancelled_snapshot_never_reaches_database() -> None:
        """A failed observation cannot become a successful empty dashboard."""
        context = _context()
        with patch.object(dbm, "status_summary", side_effect=AssertionError("database reached")) as status:
            for failure in (RuntimeError("fixture-load"), asyncio.CancelledError("fixture-cancel")):
                with (
                    patch.object(RegistryContext, "monitor_data", side_effect=failure),
                    pytest.raises(type(failure), match=str(failure)),
                ):
                    await request(context.app, _SUMMARY, headers=_IDENTITY)
            require(condition=status.call_count == 0, message="database accessed after failed observation")

    @staticmethod
    async def test_series_keeps_range_alias_partial_bounds_and_invalid_order() -> None:
        """Both series routes share bound completion without changing public names."""
        context = _context()
        snapshot = md.MonitorData({}, {}, "fixture", "fixture", 20, None)
        with (
            patch.object(RegistryContext, "monitor_data", return_value=snapshot),
            patch.object(md, "resolve_range", return_value=(10, 20)),
            patch.object(md, "domain_timeseries", return_value={"ok": True}) as series,
        ):
            path = "/dashboard/api/v1/monitoring/domains/fixture/series"
            response = await request(context.app, path + "?range=6h&since_ts=12", headers=_IDENTITY)
            require(condition=response.status_code == HTTPStatus.OK, message="partial range rejected")
            kwargs = cast("Record", series.call_args.kwargs)
            require(condition=kwargs["since_ts"] == _RANGE_START and kwargs["until_ts"] == _RANGE_END,
                    message="partial bound resolution changed")
            response = await request(context.app, path + "?since_ts=20&until_ts=10", headers=_IDENTITY)
            require(condition=response.status_code == HTTPStatus.BAD_REQUEST and series.call_count == 1,
                    message="invalid bounds reached series calculation")
            require(condition=object_or_empty(response.json())["detail"] == "invalid_range",
                    message="range error changed")
