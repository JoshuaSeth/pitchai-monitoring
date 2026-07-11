from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


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
        self._accounts_dir = data_dir / "accounts"
        self._client = httpx.Client(
            base_url=broker_url.rstrip("/"),
            headers={"Authorization": f"Bearer {admin_token}", "Accept": "application/json"},
            timeout=request_timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def read_accounts(self) -> list[dict[str, Any]]:
        if not self._accounts_dir.is_dir():
            raise RuntimeError("broker accounts directory is unavailable")

        accounts: list[dict[str, Any]] = []
        for root in sorted(path for path in self._accounts_dir.iterdir() if path.is_dir()):
            metadata_path = root / "metadata.json"
            state_path = root / "state.json"
            if not metadata_path.is_file() or not state_path.is_file():
                continue
            metadata = _read_object(metadata_path)
            state = _read_object(state_path)
            accounts.append({"metadata": metadata, "state": state})
        return accounts

    def probe_accounts(self, accounts: list[dict[str, Any]]) -> dict[str, str]:
        """Probe enabled accounts while deliberately discarding secret-bearing bodies."""

        errors: dict[str, str] = {}
        for account in accounts:
            metadata = account.get("metadata") if isinstance(account.get("metadata"), dict) else {}
            if metadata.get("enabled", True) is False:
                continue
            account_id = metadata.get("account_id")
            label = str(metadata.get("label") or account_id or "unknown")
            if not isinstance(account_id, str) or not account_id:
                errors[label] = "missing_account_id"
                continue
            try:
                with self._client.stream(
                    "POST",
                    f"/v1/admin/accounts/{quote(account_id, safe='')}/probe",
                    content=b"{}",
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                errors[label] = f"http_{exc.response.status_code}"
            except httpx.HTTPError as exc:
                errors[label] = type(exc).__name__
        return errors


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object")
    return payload
