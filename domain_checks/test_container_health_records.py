# Copyright (c) 2026 PitchAI. All rights reserved.
"""Synthetic native container observations without Docker or outgoing transport."""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import asdict
from unittest.mock import AsyncMock, patch

from .container_health_records import ContainerHealthIssue, assess_container
from .dft_test_support import require
from .docker_unix import DockerUnixResponse
from .metrics_container_health import check_container_health


class TestContainerRecords(unittest.TestCase):
    """A missed observation stays unknown and historical evidence stays distinct."""

    @staticmethod
    def test_unavailable_fields_are_unknown() -> None:
        """The three real failure callers share exactly the original null record."""
        issue = ContainerHealthIssue.unavailable(name="fixture", container_id="full-id", status="listing",
                                                error="unavailable")
        values = asdict(issue)
        for key in ("running", "restart_count", "restart_increase", "oom_killed", "health_status", "exit_code"):
            require(condition=values[key] is None, message=f"unavailable {key} became observed")
        require(condition=issue.container_id == "full-id" and issue.status == "listing"
                and issue.error == "unavailable", message="caller identity or error changed")

    @staticmethod
    def test_oom_history_and_restart_reset_are_not_current_failures() -> None:
        """A healthy running container keeps its available count after restart reset."""
        issue, count = assess_container(name="fixture", container_id="long-container-identifier", status="Up",
            data={"State": {"Running": True, "OOMKilled": True, "ExitCode": 7, "Health": {"Status": " healthy "}},
                  "RestartCount": 0}, previous_count=5)
        require(condition=issue is None and count == 0, message="historical OOM/exit/reset became a new failure")

    @staticmethod
    def test_failed_state_retains_counts_and_bad_numeric_input() -> None:
        """Unknown numeric fields remain absent while real down state stays visible."""
        issue, count = assess_container(name="fixture", container_id="long-container-identifier", status="Exited",
            data={"State": {"Running": False, "OOMKilled": "true", "ExitCode": [], "Health": {"Status": 3}},
                  "RestartCount": "5"}, previous_count=2)
        require(condition=issue is not None, message="stopped container became healthy")
        if issue is None:
            return
        expected_count, expected_increase = 5, 3
        require(condition=count == expected_count and issue.restart_increase == expected_increase
                and issue.running is False,
                message="restart delta or observed running value changed")
        require(condition=issue.exit_code is None and issue.oom_killed is None and issue.health_status is None,
                message="malformed values became confirmed inspection values")
        require(condition=issue.container_id == "long-contain", message="existing diagnostic ID bound changed")


class TestNativeContainerProbe(unittest.IsolatedAsyncioTestCase):
    """The real scheduling function reads only supplied Docker response objects."""

    @staticmethod
    async def test_failed_listing_does_not_inspect_or_reuse_prior_counts() -> None:
        """Unsuccessful list reads return the global unknown sentinel and an empty baseline."""
        read = AsyncMock(return_value=DockerUnixResponse(status=503, ok=False, data=[], error=None))
        with patch("domain_checks.metrics_container_health.asyncio.to_thread", new=read):
            issues, counts = await check_container_health(docker_socket_path="/synthetic/no-socket",
                include_name_patterns=[], exclude_name_patterns=[], monitor_all=True,
                previous_restart_counts={"old": 2})
        require(condition=len(issues) == 1 and issues[0].error == "docker_list_failed: 503"
                and issues[0].running is None and not counts, message="failed list became a healthy observation")
        read.assert_awaited_once()

    @staticmethod
    async def test_literal_pattern_selection_and_failed_inspection() -> None:
        """Invalid regex is literal, exclusions win, and malformed inspection is unknown."""
        listed = DockerUnixResponse(status=200, ok=True, data=[
            {"Id": "long-container-id", "Names": ["/svc["], "Status": " Up "},
            {"Id": "excluded", "Names": ["/svc[skip"]}, {"Id": "outside", "Names": ["/other"]},
            None, {"Id": ""},
        ], error=None)
        read = AsyncMock(side_effect=[listed, DockerUnixResponse(status=200, ok=True, data=[], error=None)])
        with patch("domain_checks.metrics_container_health.asyncio.to_thread", new=read):
            issues, counts = await check_container_health(docker_socket_path="/synthetic/no-socket",
                include_name_patterns=["svc["], exclude_name_patterns=["skip"], monitor_all=False,
                previous_restart_counts={})
        require(condition=len(issues) == 1 and issues[0].name == "svc[" and issues[0].status == "Up"
                and issues[0].error == "docker_inspect_failed: 200" and not counts,
                message="selection or unknown-inspection semantics changed")
        expected_reads = 2
        require(condition=read.await_count == expected_reads, message="unselected container was inspected")

    @staticmethod
    async def test_cancelled_inspection_releases_its_semaphore() -> None:
        """Cancellation remains visible and does not retain the admitted slot."""
        semaphore = asyncio.Semaphore(1)
        listed = DockerUnixResponse(status=200, ok=True, data=[{"Id": "fixture", "Names": ["/fixture"]}], error=None)
        read = AsyncMock(side_effect=[listed, asyncio.CancelledError])
        with (patch("domain_checks.metrics_container_health.asyncio.to_thread", new=read),
              patch("domain_checks.metrics_container_health.asyncio.Semaphore", return_value=semaphore)):
            result = await asyncio.gather(check_container_health(docker_socket_path="/synthetic/no-socket",
                include_name_patterns=[], exclude_name_patterns=[], monitor_all=True,
                previous_restart_counts={}, concurrency=1), return_exceptions=True)
        require(condition=isinstance(result[0], asyncio.CancelledError), message="inspection cancellation suppressed")
        async with asyncio.timeout(1):
            _ = await semaphore.acquire()
        semaphore.release()
