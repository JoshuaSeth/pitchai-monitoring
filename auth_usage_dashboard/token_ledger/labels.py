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
    "meituan": "Meituan LongCat",
    "other": "Other provider",
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
    ("longcat", "meituan"),
)
# Router prefixes and free-tier suffixes name a route or price, not a different model:
# ``opencode-go/longcat-2.5-preview-free`` is LongCat 2.5 Preview served free through OpenCode.
_ROUTER_PREFIXES = ("opencode-go/", "opencode/", "zen/")
_FREE_TIER_SUFFIX = "-free"
_ROUTE_PROVIDERS = {
    "codex_account": "openai",
    "astra": "openai",
    "voice": "openai",
    "claude_code": "anthropic",
    "deepseek": "deepseek",
    "zcode_account": "zhipu",
}
_MAX_LABEL = 120


def clean_text(value: str | None, *, limit: int = _MAX_LABEL) -> str | None:
    """Return printable, trimmed text within the length limit, or nothing."""
    if not isinstance(value, str):
        return None
    text = "".join(character for character in value.strip() if character.isprintable())
    return text[:limit] if text else None


def normalize_model(raw: str | None) -> str:
    """Return a stable lower-case model key; Claude aliases gain a prefix."""
    model = (clean_text(raw, limit=80) or "").lower()
    if not model:
        return UNKNOWN_MODEL
    return f"claude-{model}" if model in CLAUDE_ALIASES else model


def canonical_model(model: str) -> str:
    """Return the model key without a router prefix or a free-tier suffix."""
    for prefix in _ROUTER_PREFIXES:
        model = model.removeprefix(prefix)
    return model.removesuffix(_FREE_TIER_SUFFIX) or UNKNOWN_MODEL


def canonical_provider(model: str, fallback: str) -> str:
    """Return the vendor named by a canonical model key, or ``fallback`` when none matches."""
    for prefix, provider in _MODEL_PREFIXES:
        if model.startswith(prefix):
            return provider
    return fallback


def provider_for(model: str, route: str) -> str:
    """Derive the vendor from the model id, falling back to the runtime route.

    Returns:
        Provider key.
    """
    fallback = _ROUTE_PROVIDERS.get(route, "other")
    return canonical_provider(canonical_model(model), fallback)


def model_label(model: str) -> str:
    """Return the display label for one model key."""
    alias = model.removeprefix("claude-")
    if model.startswith("claude-") and alias in CLAUDE_ALIASES:
        return f"Claude {alias.capitalize()} (alias)"
    if model == UNKNOWN_MODEL:
        return "Unknown model"
    return model


def project_label(project: str, title: str | None) -> str:
    """Return the display label for one project key."""
    if project == NON_LANE_PROJECT:
        return NON_LANE_TITLE
    return title or project
