# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing post-transaction runner alert and optional investigation ordering."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from . import alerts
from . import db as dbm

if TYPE_CHECKING:
    from httpx import AsyncClient

    from domain_checks.event_bus_delivery import JsonObject

    from .app_context import RegistryContext
    from .dashboard_records import Record
    from .schema import RunnerCompleteRequest


@dataclass(frozen=True)
class RunnerNotifications:
    """One committed completion; settings remain late-bound between operations."""

    context: RegistryContext
    run_id: str
    request: RunnerCompleteRequest
    outcome: dbm.CompletionOutcome

    async def failure(self, client: AsyncClient) -> None:
        """Send admitted failure text before the existing optional dispatch."""
        outcome = self.outcome
        if not (outcome.alerted_down and outcome.updated and outcome.tenant_id
                and outcome.test_id and outcome.test_name):
            return
        config = cast("Record | None", await asyncio.to_thread(
            dbm.get_test_config_internal, self.context.settings, test_id=outcome.test_id,
        ))
        down_after = (
            int(cast("str | int | float", config.get("down_after_failures") or 2)) if isinstance(config, dict) else 2
        )
        test_kind = str(config.get("test_kind") or "stepflow") if isinstance(config, dict) else "stepflow"
        message = alerts.build_failure_telegram_message(
            settings=self.context.settings, tenant_id=outcome.tenant_id, test_id=outcome.test_id,
            test_name=outcome.test_name, test_kind=test_kind, run_id=self.run_id,
            fail_streak=int(outcome.fail_streak or 0), down_after_failures=down_after,
            error_kind=self.request.error_kind, error_message=self.request.error_message,
            final_url=self.request.final_url, artifacts=cast("JsonObject", self.request.artifacts),
        )
        await alerts.maybe_send_failure_alert(http_client=client, settings=self.context.settings, msg=message)
        if isinstance(config, dict) and bool(int(cast("str | int | float", config.get("dispatch_on_failure") or 0))):
            await self.dispatch(client, config, test_kind)

    async def dispatch(self, client: AsyncClient, config: Record, test_kind: str) -> None:
        """Build the admitted failure investigation after its alert has returned."""
        prompt = alerts.build_dispatch_prompt_for_failure(
            test_id=cast("str", self.outcome.test_id), test_name=cast("str", self.outcome.test_name),
            test_kind=test_kind, base_url=str(config.get("base_url") or ""), run_id=self.run_id,
            error_kind=self.request.error_kind, error_message=self.request.error_message,
            artifacts=cast("JsonObject", self.request.artifacts),
        )
        await alerts.maybe_dispatch_failure_investigation(
            http_client=client, settings=self.context.settings, prompt=prompt,
            context={
                "tenant_id": self.outcome.tenant_id, "test_id": self.outcome.test_id,
                "test_name": self.outcome.test_name, "test_kind": test_kind,
                "base_url": str(config.get("base_url") or ""), "run_id": self.run_id,
            },
        )

    async def recovery(self, client: AsyncClient) -> None:
        """Retain independent recovery admission and its fresh configuration read."""
        outcome = self.outcome
        if not (outcome.recovered_up and outcome.updated and outcome.test_id and outcome.test_name):
            return
        config = cast("Record | None", await asyncio.to_thread(
            dbm.get_test_config_internal, self.context.settings, test_id=outcome.test_id,
        ))
        if (isinstance(config, dict)
                and bool(int(cast("str | int | float", config.get("notify_on_recovery") or 0)))):
            message = alerts.build_recovery_telegram_message(
                settings=self.context.settings, test_id=outcome.test_id,
                test_name=outcome.test_name, run_id=self.run_id,
            )
            await alerts.maybe_send_failure_alert(http_client=client, settings=self.context.settings, msg=message)
