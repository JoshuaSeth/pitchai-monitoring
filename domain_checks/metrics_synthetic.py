# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable public facade for browser-based synthetic transactions."""

from __future__ import annotations

from domain_checks.synthetic_models import SyntheticTransactionResult
from domain_checks.synthetic_runner import run_synthetic_transactions

__all__ = ["SyntheticTransactionResult", "run_synthetic_transactions"]
