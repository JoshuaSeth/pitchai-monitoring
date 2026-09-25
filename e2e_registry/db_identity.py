# Copyright (c) 2026 PitchAI. All rights reserved.
"""Tenant and API-key persistence for the E2E registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e_registry.db_core import fetch_one_row, new_uuid, row_record, utc_timestamp
from e2e_registry.db_schema import registry_connection
from e2e_registry.models import AuthedTenant

if TYPE_CHECKING:
    from e2e_registry.models import DatabaseRecord
    from e2e_registry.settings import RegistrySettings


def create_tenant(settings: RegistrySettings, *, name: str) -> DatabaseRecord:
    """Persist and return a tenant.

    Returns:
        The created tenant record.
    """
    with registry_connection(settings) as connection:
        tenant_id = new_uuid()
        now = utc_timestamp()
        normalized_name = name.strip()
        connection.execute(
            "INSERT INTO tenants (id, name, created_at_ts, updated_at_ts) VALUES (?, ?, ?, ?)",
            (tenant_id, normalized_name, now, now),
        )
        return {"id": tenant_id, "name": normalized_name, "created_at_ts": now}


def create_api_key(
    settings: RegistrySettings,
    *,
    tenant_id: str,
    name: str,
    token_hash: str,
) -> DatabaseRecord:
    """Persist and return an API-key record.

    Returns:
        The created API-key record without its secret token.
    """
    with registry_connection(settings) as connection:
        api_key_id = new_uuid()
        now = utc_timestamp()
        normalized_name = name.strip()
        connection.execute(
            "INSERT INTO api_keys (id, tenant_id, name, token_hash, created_at_ts) VALUES (?, ?, ?, ?, ?)",
            (api_key_id, tenant_id, normalized_name, token_hash, now),
        )
        return {
            "id": api_key_id,
            "tenant_id": tenant_id,
            "name": normalized_name,
            "created_at_ts": now,
        }


def get_api_key_by_hash(
    settings: RegistrySettings,
    *,
    token_hash: str,
) -> AuthedTenant | None:
    """Resolve an active API key to its tenant identity.

    Returns:
        The owning tenant and key identity, or ``None`` when inactive or unknown.
    """
    with registry_connection(settings) as connection:
        row = fetch_one_row(
            connection.execute(
                "SELECT id, tenant_id FROM api_keys WHERE token_hash=? AND revoked_at_ts IS NULL",
                (token_hash,),
            ),
        )
        if row is None:
            return None
        record = row_record(row)
        return AuthedTenant(
            tenant_id=str(record["tenant_id"]),
            api_key_id=str(record["id"]),
        )
