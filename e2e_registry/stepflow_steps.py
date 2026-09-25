# Copyright (c) 2026 PitchAI. All rights reserved.
"""Per-step normalization for declarative browser test definitions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from e2e_registry.stepflow_types import StepFlowValidationError

if TYPE_CHECKING:
    from e2e_registry.models import JsonObject, JsonValue

type StepNormalizer = Callable[[JsonObject, int], JsonObject]

_SECRET_REF_RE = re.compile(r"\$\{[A-Z0-9_]{1,64}\}")
_MAXIMUM_SELECTOR_LENGTH = 500
_MAXIMUM_URL_LENGTH = 2_000
_MAXIMUM_FILL_LENGTH = 5_000
_MAXIMUM_LITERAL_FILL_LENGTH = 512
_MAXIMUM_COUNT = 10_000
_MINIMUM_VIEWPORT = 100
_MAXIMUM_VIEWPORT = 5_000
_DEFAULT_SLEEP_MS = 250
_MAXIMUM_SLEEP_MS = 30_000


def _required_text(raw_step: JsonObject, key: str, index: int, label: str) -> str:
    value = str(raw_step.get(key) or "").strip()
    if not value:
        message = f"missing_{label}[{index}]"
        raise StepFlowValidationError(message)
    return value


def _required_integer(value: JsonValue, *, index: int, label: str) -> int:
    if not isinstance(value, bool | int | float | str):
        message = f"invalid_{label}[{index}]"
        raise StepFlowValidationError(message)
    try:
        return int(value)
    except (ValueError, OverflowError) as exc:
        message = f"invalid_{label}[{index}]"
        raise StepFlowValidationError(message) from exc


def _selector(raw_step: JsonObject, index: int) -> str:
    selector = _required_text(raw_step, "selector", index, "selector")
    return selector[:_MAXIMUM_SELECTOR_LENGTH]


def _goto(raw_step: JsonObject, _index: int) -> JsonObject:
    normalized: JsonObject = {}
    url = raw_step.get("url")
    if url is not None:
        normalized["url"] = str(url).strip()[:_MAXIMUM_URL_LENGTH]
    return normalized


def _click(raw_step: JsonObject, index: int) -> JsonObject:
    selector = _selector(raw_step, index)
    return {"selector": selector}


def _fill(raw_step: JsonObject, index: int) -> JsonObject:
    selector = _selector(raw_step, index)
    text = str(raw_step.get("text") or "")
    if len(text) > _MAXIMUM_FILL_LENGTH:
        message = f"text_too_long[{index}]"
        raise StepFlowValidationError(message)
    literal_too_long = len(text) > _MAXIMUM_LITERAL_FILL_LENGTH
    if literal_too_long and not _SECRET_REF_RE.search(text):
        message = f"fill_text_must_use_secret_placeholder[{index}]"
        raise StepFlowValidationError(message)
    return {"selector": selector, "text": text}


def _press(raw_step: JsonObject, _index: int) -> JsonObject:
    normalized: JsonObject = {"key": (str(raw_step.get("key") or "").strip() or "Enter")[:80]}
    selector = str(raw_step.get("selector") or "").strip()
    if selector:
        normalized["selector"] = selector[:_MAXIMUM_SELECTOR_LENGTH]
    return normalized


def _wait_for_selector(raw_step: JsonObject, index: int) -> JsonObject:
    selector = _selector(raw_step, index)
    state = str(raw_step.get("state") or "visible").strip()[:30]
    return {"selector": selector, "state": state}


def _expect_url_contains(raw_step: JsonObject, index: int) -> JsonObject:
    value = _required_text(raw_step, "value", index, "value")
    return {"value": value[:_MAXIMUM_SELECTOR_LENGTH]}


def _expect_text(raw_step: JsonObject, index: int) -> JsonObject:
    value = _required_text(raw_step, "text", index, "text")
    return {"text": value[:_MAXIMUM_SELECTOR_LENGTH]}


def _expect_title_contains(raw_step: JsonObject, index: int) -> JsonObject:
    value = raw_step.get("text") or raw_step.get("value")
    normalized = str(value or "").strip()
    if not normalized:
        message = f"missing_text[{index}]"
        raise StepFlowValidationError(message)
    return {"text": normalized[:200]}


def _expect_selector_count(raw_step: JsonObject, index: int) -> JsonObject:
    selector = _selector(raw_step, index)
    count = _required_integer(raw_step.get("count"), index=index, label="count")
    if count < 0 or count > _MAXIMUM_COUNT:
        message = f"invalid_count[{index}]"
        raise StepFlowValidationError(message)
    return {"selector": selector, "count": count}


def _screenshot(raw_step: JsonObject, _index: int) -> JsonObject:
    name = str(raw_step.get("name") or "screenshot").strip()[:80]
    return {"name": name}


def _set_viewport(raw_step: JsonObject, index: int) -> JsonObject:
    width = _required_integer(raw_step.get("width"), index=index, label="viewport")
    height = _required_integer(raw_step.get("height"), index=index, label="viewport")
    width_valid = _MINIMUM_VIEWPORT <= width <= _MAXIMUM_VIEWPORT
    height_valid = _MINIMUM_VIEWPORT <= height <= _MAXIMUM_VIEWPORT
    if not width_valid or not height_valid:
        message = f"invalid_viewport[{index}]"
        raise StepFlowValidationError(message)
    return {"width": width, "height": height}


def _sleep(raw_step: JsonObject, _index: int) -> JsonObject:
    value = raw_step.get("ms") or _DEFAULT_SLEEP_MS
    if isinstance(value, bool | int | float | str):
        try:
            milliseconds = int(value)
        except (ValueError, OverflowError):
            milliseconds = _DEFAULT_SLEEP_MS
    else:
        milliseconds = _DEFAULT_SLEEP_MS
    bounded = max(0, min(milliseconds, _MAXIMUM_SLEEP_MS))
    return {"ms": bounded}


_NORMALIZERS: dict[str, StepNormalizer] = {
    "goto": _goto,
    "click": _click,
    "fill": _fill,
    "press": _press,
    "wait_for_selector": _wait_for_selector,
    "expect_url_contains": _expect_url_contains,
    "expect_text": _expect_text,
    "expect_title_contains": _expect_title_contains,
    "expect_selector_count": _expect_selector_count,
    "screenshot": _screenshot,
    "set_viewport": _set_viewport,
    "sleep": _sleep,
    "sleep_ms": _sleep,
}


def normalize_steps(raw_steps: list[JsonValue]) -> list[JsonObject]:
    """Return validated, bounded steps while retaining configured order.

    Raises:
        StepFlowValidationError: If a step is not a mapping or names an unknown type.
    """
    normalized_steps: list[JsonObject] = []
    for index, value in enumerate(raw_steps):
        if not isinstance(value, dict):
            message = f"invalid_step[{index}]"
            raise StepFlowValidationError(message)
        raw_step = cast("JsonObject", value)
        step_type = str(raw_step.get("type") or "").strip().lower()
        if not step_type:
            message = f"missing_step_type[{index}]"
            raise StepFlowValidationError(message)
        normalizer = _NORMALIZERS.get(step_type)
        if normalizer is None:
            message = f"unknown_step_type[{index}]: {step_type}"
            raise StepFlowValidationError(message)
        fields = normalizer(raw_step, index)
        normalized_steps.append({"type": step_type, **fields})
    return normalized_steps
