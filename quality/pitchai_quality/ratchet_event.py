# Copyright (c) 2026 PitchAI. All rights reserved.
"""Resolve the exact comparison commit from a GitHub Actions event."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pitchai_quality.ratchet_json import expect_object, expect_text

if TYPE_CHECKING:
    from pitchai_quality.ratchet_model import JsonValue

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_ZERO_SHA = "0" * 40


def validate_commit_sha(value: str, description: str) -> str:
    """Require one lowercase full Git commit SHA.

    Returns:
        The validated SHA.

    Raises:
        ValueError: If the value is not a lowercase 40-hex SHA.
    """
    if _FULL_SHA.fullmatch(value) is None:
        message = f"{description} must be a lowercase full Git commit SHA"
        raise ValueError(message)
    return value


def comparison_base(event_name: str, event: dict[str, JsonValue], activation_commit: str) -> str:
    """Resolve the changed-file base for one supported GitHub event.

    An initial branch push has an all-zero ``before`` value. That documented
    event shape compares against the immutable activation commit.

    Returns:
        A validated full commit SHA.

    Raises:
        ValueError: If the event is unsupported or a commit is malformed.
    """
    activation = validate_commit_sha(activation_commit, "activation commit")
    if event_name == "pull_request":
        pull_request = expect_object(event.get("pull_request"), "pull request event")
        base = expect_object(pull_request.get("base"), "pull request base")
        return validate_commit_sha(expect_text(base.get("sha"), "pull request base SHA"), "pull request base SHA")
    if event_name == "push":
        before = expect_text(event.get("before"), "push before SHA")
        return activation if before == _ZERO_SHA else validate_commit_sha(before, "push before SHA")
    if event_name == "workflow_dispatch":
        return activation
    message = f"unsupported GitHub event for quality ratchet: {event_name}"
    raise ValueError(message)
