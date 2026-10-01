# Copyright (c) 2026 PitchAI. All rights reserved.
"""Consume a coalesced wake hint before refreshing authoritative evidence."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def consume_proof_wake() -> None:
    """Remove the current hint under the guardian lock, before either refresh.

    The marker is never evidence or a redemption instruction. A publisher that
    replaces it after this unlink leaves a new hint for the next service run.
    An absent hint or directory does not prevent ordinary timer evaluation.
    Other filesystem errors propagate so systemd can bound failed activations.
    """
    configured = os.environ.get("AUTH_RESET_GUARDIAN_PROOF_WAKE_PATH")
    if not configured:
        return
    path = Path(configured)
    try:
        path.unlink()
    except FileNotFoundError:
        logging.getLogger(__name__).info("No execution-proof wake hint to consume")
        return
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
