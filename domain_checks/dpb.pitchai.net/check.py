# Copyright (c) 2026 PitchAI. All rights reserved.
"""Strict monitoring contract for the Deplanbook alias domain."""

from domain_checks.domain_contract_templates import build_planbook_check

CHECK = build_planbook_check(
    domain="dpb.pitchai.net",
    url="https://dpb.pitchai.net",
    expected_final_host_suffix="deplanbook.com",
)
