# Copyright (c) 2026 PitchAI. All rights reserved.
"""Catalog, inventory, and audit safety tests for the ASTRA watch."""

from __future__ import annotations

from astra_model_watch.audit import AuditError, AuditLog
from astra_model_watch.catalog import (
    CatalogClient,
    catalog_url,
)
from astra_model_watch.catalog_transport import CATALOG_BASE_URL, CatalogError
from astra_model_watch.inventory import load_broker_accounts
from astra_model_watch.types import BrokerAccount
from tests.astra_watch_support import (
    RecordingTransport,
    make_account,
    private_paths,
    temporary_path,
)


def test_catalog_request_is_exact_get_contract_with_account_isolation() -> None:
    """Use one account's bearer/header only on the exact model-list URL."""
    with temporary_path() as root:
        accounts_dir, _, _ = private_paths(root)
        make_account(accounts_dir, "acc-a", "A", enabled=True, token="access-a")
        account = load_broker_accounts(accounts_dir)[0]
        transport = RecordingTransport({"models": []})

        result = CatalogClient(transport).fetch(
            account,
            client_version="0.137.0",
            timeout_seconds=12.0,
        )

        assert result.model_count == 0
        assert transport.calls == [
            (
                f"{CATALOG_BASE_URL}?client_version=0.137.0",
                {
                    "Accept": "application/json",
                    "Authorization": "Bearer access-a",
                    "Cache-Control": "no-cache",
                    "ChatGPT-Account-ID": "acc-a",
                    "User-Agent": "codex-cli/0.137.0 pitchai-astra-model-watch",
                },
                12.0,
            ),
        ]


def test_catalog_url_rejects_unsafe_client_versions() -> None:
    """Reject version values that could alter the allowlisted URL shape."""
    for version in ("", "0.1/reset", "https://evil.test", "0.1?claim=1"):
        try:
            _ = catalog_url(version)
        except CatalogError as exc:
            assert exc.error_code == "invalid_client_version"
        else:
            raise AssertionError(f"unsafe version accepted: {version}")


def test_astra_detection_is_case_insensitive_across_id_and_name_fields() -> None:
    """Match ASTRA case-insensitively across supported identity fields."""
    with temporary_path() as root:
        accounts_dir, _, _ = private_paths(root)
        make_account(accounts_dir, "acc-a", "A", enabled=True, token="access-a")
        account = load_broker_accounts(accounts_dir)[0]
        transport = RecordingTransport(
            {
                "models": [
                    {"slug": "gpt-normal", "display_name": "Normal"},
                    {"slug": "codex-astra-preview", "display_name": "ASTRA Preview"},
                    {"id": "internal-AstRa-canary", "name": "Canary"},
                ],
            },
        )

        result = CatalogClient(transport).fetch(
            account,
            client_version="0.137.0",
            timeout_seconds=10.0,
        )

        assert result.model_count == 3
        assert [match.identifier for match in result.matches] == [
            "codex-astra-preview",
            "internal-AstRa-canary",
        ]
        assert result.matches[0].matched_fields == ("slug", "display_name")


def test_audit_log_refuses_sensitive_keys_and_values() -> None:
    """Fail closed before a token-shaped key or known secret reaches disk."""
    with temporary_path() as root:
        _, log_path, _ = private_paths(root)
        audit = AuditLog(log_path)

        try:
            audit.append({"access_token": "secret"})
        except AuditError as exc:
            assert str(exc) == "sensitive_key_refused"
        else:
            raise AssertionError("sensitive audit key was accepted")
        try:
            audit.append(
                {"event_type": "bad", "value": "Bearer secret"},
                sensitive_values=["secret"],
            )
        except AuditError as exc:
            assert str(exc) == "sensitive_value_refused"
        else:
            raise AssertionError("sensitive audit value was accepted")


def test_inventory_exposes_only_sanitized_auth_metadata() -> None:
    """Keep bearers out of account representations while retaining provenance."""
    with temporary_path() as root:
        accounts_dir, _, _ = private_paths(root)
        make_account(accounts_dir, "acc-a", "A", enabled=True, token="access-a")

        account = load_broker_accounts(accounts_dir)[0]

        assert isinstance(account, BrokerAccount)
        assert account.directory_name == "acc-a"
        assert account.account_header_id == "acc-a"
        assert account.account_id_source == "id_token.signed_auth_claim"
        assert account.auth_file_mode == "0600"
        assert "access-a" not in repr(account)
