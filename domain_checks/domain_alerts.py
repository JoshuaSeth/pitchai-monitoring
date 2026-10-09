# Copyright (c) 2026 PitchAI. All rights reserved.
"""Existing domain warning text and inventory-owned routing decision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .dispatch_transport import send_telegram_message_chunked
from .message_performance import format_ms as _format_ms

if TYPE_CHECKING:
    from httpx import AsyncClient

    from .common_check import DomainCheckResult
    from .domain_entries import DomainEntryConfig
    from .event_bus_delivery import JsonObject
    from .telegram import TelegramConfig

LOGGER = logging.getLogger("service-monitoring")


def build_down_alert_message(result: DomainCheckResult) -> str:
    """Return the existing bounded domain warning without choosing an audience."""
    d = result.details or {}
    lines = [f"{result.domain} is DOWN ❌", f"Reason: {result.reason}"]

    fail_streak = d.get("fail_streak")
    down_after = d.get("down_after_failures")
    if isinstance(fail_streak, int) and isinstance(down_after, int) and down_after > 1:
        lines.append(f"Debounce: fail_streak={fail_streak}/{down_after}")

    status_code = d.get("status_code")
    if status_code is not None:
        lines.append(f"HTTP: {status_code} ({_format_ms(d.get('http_elapsed_ms'))})")

    browser_status = d.get("http_status")
    if browser_status is not None:
        lines.append(f"Browser: {browser_status} ({_format_ms(d.get('browser_elapsed_ms'))})")

    final_url = d.get("final_url")
    if isinstance(final_url, str) and final_url:
        lines.append(f"Final URL: {final_url}")

    if d.get("final_host_ok") is False:
        final_host = d.get("final_host")
        expected_suffix = d.get("expected_final_host_suffix")
        lines.append(f"Final host mismatch: got={final_host} expected_suffix={expected_suffix}")

    if d.get("title_ok") is False:
        lines.append(f"Title mismatch: {d.get('title')!r}")

    error = d.get("error")
    if isinstance(error, str) and error.strip():
        lines.append(f"Error: {error.strip()[:500]}")

    lines.extend(_content_failure_lines(d))
    return "\n".join(lines).strip()


def _content_failure_lines(details: JsonObject) -> list[str]:
    lines: list[str] = []
    for key, label, limit in (
        ("forbidden_hits", "Forbidden text hit", 8),
        ("missing_selectors_all", "Missing selectors", 5),
        ("missing_text", "Missing text", 5),
    ):
        values = details.get(key) or []
        if isinstance(values, list) and values:
            rendered = ", ".join(str(value) for value in values[:limit])
            lines.append(f"{label}: {rendered}")
    return lines


async def route_domain_telegram_alert(
    *,
    http_client: AsyncClient,
    telegram_cfg: TelegramConfig,
    entry: DomainEntryConfig,
    message: str,
) -> tuple[bool, list[JsonObject]] | None:
    """Return the existing send observation, or None when inventory suppresses it."""
    if not entry.routes_telegram:
        LOGGER.info(
            "Telegram alert suppressed by inventory policy domain=%s mode=%s reason=%s",
            entry.domain,
            entry.alert_policy.telegram,
            entry.alert_policy.reason,
        )
        return None
    return await send_telegram_message_chunked(http_client, telegram_cfg, message)
