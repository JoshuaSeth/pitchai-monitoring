# Copyright (c) 2026 PitchAI. All rights reserved.
"""Read broker state and request safe analytics probes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

from .json_contract import decode_document

if TYPE_CHECKING:
    from pathlib import Path

    from .json_contract import JsonObject


class SourceDocumentError(RuntimeError):
    """A broker source document violated its required JSON shape."""


class BrokerStateSource:
    """Read only redacted broker files and trigger no-generation usage probes."""

    def __init__(
        self,
        *,
        data_dir: Path,
        broker_url: str,
        admin_token: str,
        request_timeout_seconds: float,
    ) -> None:
        """Initialize this instance."""
        self._accounts_dir: Path = data_dir / "accounts"
        self._client: httpx.Client = httpx.Client(
            base_url=broker_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Accept": "application/json",
            },
            timeout=request_timeout_seconds,
        )

    def close(self) -> None:
        """Close close."""
        self._client.close()

    def read_accounts(self) -> list[JsonObject]:
        """Read read accounts.

        Returns:
            The resulting collection.

        Raises:
            RuntimeError: If the operation cannot satisfy its runtime contract.

        """
        if not self._accounts_dir.is_dir():
            msg = "broker accounts directory is unavailable"
            raise RuntimeError(msg)

        accounts: list[JsonObject] = []
        for root in sorted(path for path in self._accounts_dir.iterdir() if path.is_dir()):
            metadata_path = root / "metadata.json"
            state_path = root / "state.json"
            if not metadata_path.is_file() or not state_path.is_file():
                continue
            metadata = _read_object(metadata_path)
            state = _read_object(state_path)
            accounts.append({"metadata": metadata, "state": state})
        return accounts

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Probe enabled accounts while deliberately discarding secret-bearing bodies.

        Returns:
            The resulting collection.

        """
        return self._probe_accounts(accounts, endpoint="probe")

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Refresh redacted token history and reset-bank state.

        Returns:
            The resulting collection.

        """
        return self._probe_accounts(accounts, endpoint="analytics-probe")

    def _probe_accounts(
        self,
        accounts: list[JsonObject],
        *,
        endpoint: str,
    ) -> dict[str, str]:
        """Call one broker probe endpoint without reading its response body.

        Returns:
            The resulting collection.

        """
        errors: dict[str, str] = {}
        for account in accounts:
            metadata = _object(account, "metadata")
            if metadata.get("enabled", True) is False:
                continue
            account_id = metadata.get("account_id")
            label = str(metadata.get("label") or account_id or "unknown")
            if not isinstance(account_id, str) or not account_id:
                errors[label] = "missing_account_id"
                continue
            try:
                self._probe_account(account_id, endpoint=endpoint)
            except httpx.HTTPStatusError as exc:
                errors[label] = f"http_{exc.response.status_code}"
            except httpx.HTTPError as exc:
                errors[label] = type(exc).__name__
        return errors

    def _probe_account(self, account_id: str, *, endpoint: str) -> None:
        """Send one account probe and require a successful status."""
        with self._client.stream(
            "POST",
            f"/v1/admin/accounts/{quote(account_id, safe='')}/{endpoint}",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        ) as response:
            _ = response.raise_for_status()


def _read_object(path: Path) -> JsonObject:
    payload = decode_document(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"{path.name} must contain a JSON object"
        raise SourceDocumentError(msg)
    return payload


def _object(container: JsonObject, key: str) -> JsonObject:
    """Return one nested JSON object or an empty object when absent."""
    value = container.get(key)
    return value if isinstance(value, dict) else {}
