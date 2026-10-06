# Copyright (c) 2026 PitchAI. All rights reserved.
"""Provider color families and per-model shades for the token ledger.

Each provider owns one color family (OpenAI cyan to navy, Anthropic yellow to
brown, DeepSeek violet, Zhipu green, Xiaomi magenta, Meituan LongCat chartreuse). Within a family a darker
shade means a heavier, more capable model, ordered by the Artificial Analysis
Intelligence Index (artificialanalysis.ai/leaderboards/models, max effort, read
2026-10-05). Shades step at least 0.06 in OKLCH lightness so neighbours stay
distinguishable; the legend, tooltip and totals table carry the names.
"""

from __future__ import annotations

from typing import NamedTuple

OTHER_COLOR = "#9b9a94"
PROVIDER_COLORS = {
    "openai": "#2a6fdb",
    "anthropic": "#f07a24",
    "deepseek": "#6a55d8",
    "zhipu": "#1e9a5a",
    "xiaomi": "#d1508f",
    "google": "#0f8b8d",
    "moonshot": "#5b6b7a",
    "meituan": "#8aa61c",
}
# Unlisted models of a known provider take the family's neutral middle shade.
FAMILY_FALLBACK = {
    "openai": "#5b8fd9",
    "anthropic": "#e0662a",
    "deepseek": "#6a55d8",
    "zhipu": "#1e9a5a",
    "xiaomi": "#d1508f",
    "google": "#0f8b8d",
    "moonshot": "#5b6b7a",
    "meituan": "#8aa61c",
}


class ModelShade(NamedTuple):
    """One model's family shade, AA index (when listed) and capability order key."""

    color: str
    intelligence: float | None
    order: float


# Order key: AA index, except where noted. Proxies use the closest AA listing.
MODEL_SHADES = {
    "gpt-6-astra": ModelShade("#1d3a8f", 53.0, 53.0),  # navy (darkest)
    "gpt-5.6-sol": ModelShade("#2a6fdb", 52.0, 52.0),  # proxy: GPT-6.1 Sol
    "gpt-5.6-terra": ModelShade("#2fa0ea", 42.0, 42.0),  # azure
    "gpt-5.6-luna": ModelShade("#38c6d6", 38.0, 38.0),  # cyan; proxy: GPT-6 Luna
    # Operator choice 2026-10-05: Fable is the heavier model (brown) although AA lists it below Opus.
    "claude-fable": ModelShade("#8a4b1a", 53.0, 60.0),
    "claude-opus": ModelShade("#d03a2f", 58.0, 58.0),  # red
    "claude-sonnet": ModelShade("#f07a24", 56.0, 56.0),  # orange
    "claude-haiku": ModelShade("#d9a100", 17.0, 17.0),  # yellow
    "deepseek-pro": ModelShade("#4b33a8", None, 50.0),
    "deepseek-flash": ModelShade("#8a6fe8", 39.0, 39.0),  # AA: DeepSeek V4.1 Flash
    "glm-5.3": ModelShade("#0e6b3d", 45.0, 45.0),
    "glm-5.3-flash": ModelShade("#3dbb76", 42.0, 42.0),
    "mimo-v2.6-pro": ModelShade("#a02368", 46.0, 46.0),
    "mimo-v2.6-flash": ModelShade("#e86aa8", None, 35.0),
    # AA has no LongCat 2.5 listing yet (checked 2026-10-06; LongCat 2.0 scores 19), so no index is shown.
    "longcat-2.5-preview": ModelShade("#6b8a12", None, 45.0),
}


def model_shade(model: str, provider: str) -> ModelShade:
    """Return the family shade of one model; unlisted models get the family middle."""
    listed = MODEL_SHADES.get(model)
    if listed is not None:
        return listed
    return ModelShade(FAMILY_FALLBACK.get(provider, OTHER_COLOR), None, 0.0)
