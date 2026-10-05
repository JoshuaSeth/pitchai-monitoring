# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable provider, model, route and project labels for ledger rows."""

from __future__ import annotations

NON_LANE_PROJECT = "_nonlane"
NON_LANE_TITLE = "(non-lane)"
UNKNOWN_MODEL = "unknown"
CLAUDE_ALIASES = frozenset({"opus", "sonnet", "haiku", "fable"})

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "zhipu": "Zhipu GLM",
    "xiaomi": "Xiaomi MiMo",
    "google": "Google",
    "moonshot": "Moonshot",
    "other": "Other provider",
}
# Fixed categorical slot per provider so a provider keeps its color in every range.
PROVIDER_SLOTS = {
    "openai": 0,
    "anthropic": 1,
    "deepseek": 2,
    "zhipu": 3,
    "xiaomi": 4,
    "google": 5,
    "moonshot": 6,
    "other": 6,
}
ROUTE_LABELS = {
    "codex_account": "Codex account broker",
    "astra": "Astra owner",
    "claude_code": "Claude Code owner",
    "deepseek": "DeepSeek owner",
    "opencode_go": "OpenCode Go owner",
    "zcode_account": "ZCode account owner",
    "voice": "ORI voice",
}
_MODEL_PREFIXES = (
    ("gpt", "openai"),
    ("codex", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("claude", "anthropic"),
    ("deepseek", "deepseek"),
    ("glm", "zhipu"),
    ("mimo", "xiaomi"),
    ("gemini", "google"),
    ("kimi", "moonshot"),
)
_ROUTE_PROVIDERS = {
    "codex_account": "openai",
    "astra": "openai",
    "voice": "openai",
    "claude_code": "anthropic",
    "deepseek": "deepseek",
    "zcode_account": "zhipu",
}
_MAX_LABEL = 120


def clean_text(value: object, *, limit: int = _MAX_LABEL) -> str | None:
    """Return printable, trimmed text within the length limit, or nothing."""
    if not isinstance(value, str):
        return None
    text = "".join(character for character in value.strip() if character.isprintable())
    return text[:limit] if text else None


def normalize_model(raw: object) -> str:
    """Return a stable lower-case model key; Claude aliases gain a prefix."""
    model = (clean_text(raw, limit=80) or "").lower()
    if not model:
        return UNKNOWN_MODEL
    return f"claude-{model}" if model in CLAUDE_ALIASES else model


def provider_for(model: str, route: str) -> str:
    """Derive the vendor from the model id, falling back to the runtime route.

    Returns:
        Provider key.
    """
    for prefix, provider in _MODEL_PREFIXES:
        if model.startswith(prefix):
            return provider
    return _ROUTE_PROVIDERS.get(route, "other")


def model_label(model: str) -> str:
    """Return the display label for one model key."""
    alias = model.removeprefix("claude-")
    if model.startswith("claude-") and alias in CLAUDE_ALIASES:
        return f"Claude {alias.capitalize()} (alias)"
    if model == UNKNOWN_MODEL:
        return "Unknown model"
    return model


def provider_label(provider: str) -> str:
    """Return the display label for one provider key."""
    return PROVIDER_LABELS.get(provider, provider)


def project_label(project: str, title: str | None) -> str:
    """Return the display label for one project key."""
    if project == NON_LANE_PROJECT:
        return NON_LANE_TITLE
    return title or project
