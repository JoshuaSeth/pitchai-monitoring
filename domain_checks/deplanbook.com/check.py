# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict monitoring contract for the canonical Deplanbook domain."""

from domain_checks.domain_contract_templates import build_planbook_check

CHECK = build_planbook_check(
    domain="deplanbook.com",
    url="https://deplanbook.com",
)
