# Copyright (c) 2026 PitchAI. All rights reserved.
"""Infrastructure gateway to the broker: redacted account files and no-generation probes."""

from __future__ import annotations

import json
from importlib import import_module
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

from .service_failures import FailureCapture
from .timeseries_types import optional_object

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from .timeseries_types import JsonObject, JsonValue

_HTTPX = cast("dict[str, object]", vars(import_module("httpx")))
_HTTP_CLIENT = cast("type[httpx.Client]", _HTTPX["Client"])
_HTTP_ERROR = cast("type[httpx.HTTPError]", _HTTPX["HTTPError"])
_HTTP_STATUS_ERROR = cast("type[httpx.HTTPStatusError]", _HTTPX["HTTPStatusError"])


class BrokerStateSource:
    """Read only redacted broker files and trigger no-generation usage probes."""

    _accounts_dir: Path
    _client: httpx.Client

    def __init__(
        self,
        *,
        data_dir: Path,
        broker_url: str,
        admin_token: str,
        request_timeout_seconds: float,
    ) -> None:
        """Bind the broker's account directory and an authenticated broker admin client."""
        self._accounts_dir = data_dir / "accounts"
        self._client = _HTTP_CLIENT(
            base_url=broker_url.rstrip("/"),
            headers={"Authorization": f"Bearer {admin_token}", "Accept": "application/json"},
            timeout=request_timeout_seconds,
        )

    def close(self) -> None:
        """Close the broker client."""
        self._client.close()

    def read_accounts(self) -> list[JsonObject]:
        """Read the metadata and state of every account directory that has both files.

        Returns:
            Accounts in directory-name order; ``auth.json`` and other files are never read.

        Raises:
            RuntimeError: If the accounts directory is missing or a file is not a JSON object.
        """
        if not self._accounts_dir.is_dir():
            message = "broker accounts directory is unavailable"
            raise RuntimeError(message)

        directories = sorted(path for path in self._accounts_dir.iterdir() if path.is_dir())
        accounts: list[JsonObject] = []
        for directory in directories:
            metadata_path = directory / "metadata.json"
            state_path = directory / "state.json"
            if metadata_path.is_file() and state_path.is_file():
                accounts.append({"metadata": _read_object(metadata_path), "state": _read_object(state_path)})
        return accounts

    def probe_accounts(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Probe enabled accounts while deliberately discarding secret-bearing bodies.

        Returns:
            Redacted probe failures keyed by account label.
        """
        return self._probe_accounts(accounts, endpoint="probe")

    def probe_analytics(self, accounts: list[JsonObject]) -> dict[str, str]:
        """Refresh redacted token history and reset-bank state.

        Returns:
            Redacted probe failures keyed by account label.
        """
        return self._probe_accounts(accounts, endpoint="analytics-probe")

    def _probe_accounts(self, accounts: list[JsonObject], *, endpoint: str) -> dict[str, str]:
        errors: dict[str, str] = {}
        for account in accounts:
            metadata = optional_object(account.get("metadata"))
            if metadata.get("enabled", True) is False:
                continue
            account_id = metadata.get("account_id")
            label = str(metadata.get("label") or account_id or "unknown")
            if not isinstance(account_id, str) or not account_id:
                errors[label] = "missing_account_id"
                continue
            failure = self._post_probe(account_id, endpoint=endpoint)
            if failure is not None:
                errors[label] = failure
        return errors

    def _post_probe(self, account_id: str, *, endpoint: str) -> str | None:
        """Call one broker probe endpoint without reading its response body.

        Returns:
            None on success, otherwise ``http_<status>`` or the transport error name.
        """
        path = f"/v1/admin/accounts/{quote(account_id, safe='')}/{endpoint}"
        with (
            FailureCapture(_HTTP_ERROR) as failure,
            self._client.stream(
                "POST",
                path,
                content=b"{}",
                headers={"Content-Type": "application/json"},
            ) as response,
        ):
            _ = response.raise_for_status()
        error = failure.error
        if error is None:
            return None
        if isinstance(error, _HTTP_STATUS_ERROR):
            return f"http_{error.response.status_code}"
        return type(error).__name__


def _read_object(path: Path) -> JsonObject:
    payload = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if isinstance(payload, dict):
        return payload
    message = f"{path.name} must contain a JSON object"
    raise RuntimeError(message)
