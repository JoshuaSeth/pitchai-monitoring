# Copyright (c) 2026 PitchAI. All rights reserved.
"""Capture spending evidence from the existing authenticated usage GET."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast, final

from .clients import JsonHttpTransport
from .funded_capacity import FundedCapacity, FundedUsageDocument, sanitize_funded_capacity
from .usage_credits import usage_credits

JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None


@dataclass
class FundedUsageTransport(JsonHttpTransport):
    """Delegate unchanged requests and retain only sanitized usage capacity."""

    delegate: JsonHttpTransport
    capacity: FundedCapacity = field(default_factory=lambda: FundedCapacity(
        credits="unknown", models="unknown", spend_control="unknown",
    ), init=False)

    spendable_credits: bool = field(default=False, init=False)

    @final
    def request(
        self, *, method: str, url: str, endpoint: str, headers: dict[str, str],
        **options: dict[str, JsonValue] | bool | None,
    ) -> dict[str, JsonValue]:
        """Read the same provider payload without extra traffic or changed affinity.

        Returns:
            The unchanged delegate response; failures propagate to the existing IO edge.
        """
        response = cast("dict[str, JsonValue]", self.delegate.request(
            method=method, url=url, endpoint=endpoint, headers=headers,
            payload=cast("dict[str, JsonValue] | None", options.get("payload")),
            ambiguous_on_failure=cast("bool", options.get("ambiguous_on_failure", False)),
        ))
        if endpoint == "provider_usage":
            self.spendable_credits = usage_credits(response)["usable"]
            fields = FundedUsageDocument(
                model_usage=response.get("model_usage"), spend_control=response.get("spend_control"),
            )
            if "credits" in response:
                fields["credits"] = response["credits"]
            self.capacity = sanitize_funded_capacity(fields)
        return response
