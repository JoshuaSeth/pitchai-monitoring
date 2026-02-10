from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import yaml


_ALLOWED_STEP_TYPES = {
    "goto",
    "click",
    "fill",
    "press",
    "wait_for_selector",
    "expect_url_contains",
    "expect_text",
    # extensions for external devs:
    "expect_title_contains",
    "expect_selector_count",
    "screenshot",
    "set_viewport",
    "sleep",
    "sleep_ms",
}

_SECRET_REF_RE = re.compile(r"\$\{[A-Z0-9_]{1,64}\}")


@dataclass(frozen=True)
class StepFlowValidationError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


def _ensure_http_url(url: str) -> None:
    s = str(url or "").strip()
    if not s:
        raise StepFlowValidationError("missing_base_url")
    parts = urlsplit(s)
    if (parts.scheme or "").lower() not in {"http", "https"}:
        raise StepFlowValidationError("invalid_base_url_scheme")
    if not parts.netloc:
        raise StepFlowValidationError("invalid_base_url_host")


def parse_definition_bytes(raw: bytes, *, content_type: str | None = None) -> dict[str, Any]:
    """
    Accept YAML or JSON and normalize into a dict:
      {"name": "...", "steps": [ ... ]}
    """
    txt = (raw or b"").decode("utf-8", errors="replace").strip()
    if not txt:
        raise StepFlowValidationError("empty_definition")

    data: Any = None
    # Prefer JSON when content-type explicitly says so.
    if content_type and "json" in str(content_type).lower():
        try:
            data = json.loads(txt)
        except Exception as exc:
            raise StepFlowValidationError(f"invalid_json: {exc}") from exc
    else:
        # YAML parser can also parse JSON.
        try:
            data = yaml.safe_load(txt)
        except Exception as exc:
            raise StepFlowValidationError(f"invalid_yaml: {exc}") from exc

    if not isinstance(data, dict):
        raise StepFlowValidationError("definition_must_be_object")
    return data


def validate_definition(defn: dict[str, Any]) -> dict[str, Any]:
    """
    Validates and returns a normalized definition dict.
    """
    if not isinstance(defn, dict):
        raise StepFlowValidationError("definition_must_be_object")

    name = str(defn.get("name") or defn.get("test_name") or "test").strip()[:120]
    steps = defn.get("steps")
    if not isinstance(steps, list) or not steps:
        raise StepFlowValidationError("missing_steps")
    if len(steps) > 60:
        raise StepFlowValidationError("too_many_steps")

    norm_steps: list[dict[str, Any]] = []
    for idx, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            raise StepFlowValidationError(f"invalid_step[{idx}]")
        typ = str(raw_step.get("type") or "").strip().lower()
        if not typ:
            raise StepFlowValidationError(f"missing_step_type[{idx}]")
        if typ not in _ALLOWED_STEP_TYPES:
            raise StepFlowValidationError(f"unknown_step_type[{idx}]: {typ}")

        step: dict[str, Any] = {"type": typ}

        if typ == "goto":
            url = raw_step.get("url")
            if url is not None:
                step["url"] = str(url).strip()[:2000]

        elif typ in {"click"}:
            sel = str(raw_step.get("selector") or "").strip()
            if not sel:
                raise StepFlowValidationError(f"missing_selector[{idx}]")
            step["selector"] = sel[:500]

        elif typ in {"fill"}:
            sel = str(raw_step.get("selector") or "").strip()
            if not sel:
                raise StepFlowValidationError(f"missing_selector[{idx}]")
            text = raw_step.get("text")
            # Allow secret placeholders; validate length only.
            s_text = str(text or "")
            if len(s_text) > 5000:
                raise StepFlowValidationError(f"text_too_long[{idx}]")
            # Minimal guardrail: prevent huge literal secrets from being embedded.
            if len(s_text) > 0 and not _SECRET_REF_RE.search(s_text) and len(s_text) > 512:
                raise StepFlowValidationError(f"fill_text_must_use_secret_placeholder[{idx}]")
            step["selector"] = sel[:500]
            step["text"] = s_text

        elif typ == "press":
            sel = str(raw_step.get("selector") or "").strip()
            if sel:
                step["selector"] = sel[:500]
            key = str(raw_step.get("key") or "").strip() or "Enter"
            step["key"] = key[:80]

        elif typ == "wait_for_selector":
            sel = str(raw_step.get("selector") or "").strip()
            if not sel:
                raise StepFlowValidationError(f"missing_selector[{idx}]")
            state = str(raw_step.get("state") or "visible").strip()
            step["selector"] = sel[:500]
            step["state"] = state[:30]

        elif typ == "expect_url_contains":
            value = str(raw_step.get("value") or "").strip()
            if not value:
                raise StepFlowValidationError(f"missing_value[{idx}]")
            step["value"] = value[:500]

        elif typ == "expect_text":
            value = str(raw_step.get("text") or "").strip()
            if not value:
                raise StepFlowValidationError(f"missing_text[{idx}]")
            step["text"] = value[:500]

        elif typ == "expect_title_contains":
            value = str(raw_step.get("text") or raw_step.get("value") or "").strip()
            if not value:
                raise StepFlowValidationError(f"missing_text[{idx}]")
            step["text"] = value[:200]

        elif typ == "expect_selector_count":
            sel = str(raw_step.get("selector") or "").strip()
            if not sel:
                raise StepFlowValidationError(f"missing_selector[{idx}]")
            try:
                count = int(raw_step.get("count"))
            except Exception as exc:
                raise StepFlowValidationError(f"invalid_count[{idx}]") from exc
            if count < 0 or count > 10_000:
                raise StepFlowValidationError(f"invalid_count[{idx}]")
            step["selector"] = sel[:500]
            step["count"] = count

        elif typ == "screenshot":
            name2 = str(raw_step.get("name") or "screenshot").strip()[:80]
            step["name"] = name2

        elif typ == "set_viewport":
            try:
                w = int(raw_step.get("width"))
                h = int(raw_step.get("height"))
            except Exception as exc:
                raise StepFlowValidationError(f"invalid_viewport[{idx}]") from exc
            if not (100 <= w <= 5000 and 100 <= h <= 5000):
                raise StepFlowValidationError(f"invalid_viewport[{idx}]")
            step["width"] = w
            step["height"] = h

        elif typ in {"sleep", "sleep_ms"}:
            try:
                ms = int(raw_step.get("ms") or 250)
            except Exception:
                ms = 250
            ms = max(0, min(ms, 30_000))
            step["ms"] = ms

        norm_steps.append(step)

    return {"name": name, "steps": norm_steps}


def validate_base_url(base_url: str) -> str:
    _ensure_http_url(base_url)
    return str(base_url).strip()

