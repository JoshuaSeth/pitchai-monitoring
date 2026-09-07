# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable organization decision fingerprint construction."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, TypedDict

from .models import stable_hash, utc_iso

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from .models import AccountObservation, ResetCredit
    from .organization_capacity import AccountCapacityEvidence, CapacityState


class RedemptionSelectionLike(Protocol):
    """Structural selection view that keeps policy imports acyclic."""

    @property
    def observation(self) -> AccountObservation:
        """Return the selected account observation."""
        raise NotImplementedError

    @property
    def credit(self) -> ResetCredit:
        """Return the exact selected credit."""
        raise NotImplementedError

    @property
    def weekly_reset_at(self) -> datetime:
        """Return the selected account's natural weekly reset."""
        raise NotImplementedError


class DecisionKeySelection(TypedDict):
    """Exact selected identity included in a coordination fingerprint."""

    account_ref: str
    credit_ref: str
    expires_at: str | None
    weekly_reset_at: str


class DecisionKeyAccount(TypedDict):
    """One account's capacity evidence included in a coordination fingerprint."""

    account_ref: str
    state: CapacityState
    exhausted_window_resets: list[int]
    weekly_reset_at: str | None


class DecisionKeyPayload(TypedDict):
    """Complete stable input to the organization decision hash."""

    accounts: list[DecisionKeyAccount]
    selection: DecisionKeySelection | None


def organization_decision_key(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    selection: RedemptionSelectionLike | None,
) -> str:
    """Hash all usable evidence and the exact selected identity.

    Returns:
        A deterministic secret-safe SHA-256 coordination key.
    """
    payload = _decision_key_payload(evidence=evidence, selection=selection)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return stable_hash(serialized)


def _decision_key_payload(
    *,
    evidence: Sequence[AccountCapacityEvidence],
    selection: RedemptionSelectionLike | None,
) -> DecisionKeyPayload:
    selected: DecisionKeySelection | None = None
    if selection is not None:
        selected = {
            "account_ref": selection.observation.descriptor.account_ref,
            "credit_ref": selection.credit.credit_ref,
            "expires_at": (
                utc_iso(selection.credit.expires_at)
                if selection.credit.expires_at
                else None
            ),
            "weekly_reset_at": utc_iso(selection.weekly_reset_at),
        }
    accounts: list[DecisionKeyAccount] = []
    for item in evidence:
        if item.state == "disabled":
            continue
        accounts.append(
            {
                "account_ref": item.account_ref,
                "state": item.state,
                "exhausted_window_resets": list(item.exhausted_window_resets),
                "weekly_reset_at": (
                    utc_iso(item.weekly_reset_at) if item.weekly_reset_at else None
                ),
            },
        )
    return {"accounts": accounts, "selection": selected}
