# Copyright (c) 2026 PitchAI. All rights reserved.
"""Typed dynamic boundary for hotpath persistence and snapshot modules."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from .hotpath_contract_runtime import HotpathInventory, HotpathLane, HotpathReport
    from .json_types import JsonObject


class IngestedReport(Protocol):
    """Secret-free result of one durable report ingestion."""

    @property
    def duplicate(self) -> bool:
        """Return whether the exact report was already retained."""
        raise NotImplementedError

    @property
    def receipt(self) -> JsonObject:
        """Return the stable report receipt."""
        raise NotImplementedError


class _CodecModule(Protocol):
    def decode_object(self, document: str) -> JsonObject:
        """Decode one persisted strict-JSON object."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _StoreReadModule(Protocol):
    def build_hotpath_snapshot(
        self,
        db_path: str,
        inventory: HotpathInventory,
        *,
        now_ts: float,
    ) -> JsonObject:
        """Build the current dashboard projection."""
        raise NotImplementedError

    def contract_name(self) -> str:
        """Return the boundary contract name."""
        raise NotImplementedError


class _StoreSchemaModule(Protocol):
    def connect(self, db_path: str) -> sqlite3.Connection:
        """Open one configured hotpath database connection."""
        raise NotImplementedError

    def row_string(self, row: sqlite3.Row, key: str) -> str:
        """Read one required string field from a database row."""
        raise NotImplementedError

    def row_optional_string(self, row: sqlite3.Row, key: str) -> str | None:
        """Read one nullable string field from a database row."""
        raise NotImplementedError

    def row_integer(self, row: sqlite3.Row, key: str) -> int:
        """Read one required integer field from a database row."""
        raise NotImplementedError

    def row_value(self, row: sqlite3.Row, key: str) -> str | int | float | bytes | None:
        """Read one narrowed SQLite scalar from a database row."""
        raise NotImplementedError


class _StoreWriteModule(Protocol):
    @staticmethod
    def ingest_report(
        db_path: str,
        inventory: HotpathInventory,
        report: HotpathReport,
        lane: HotpathLane | None,
        *,
        received_at_ts: float,
    ) -> IngestedReport:
        """Retain one report and update current and incident state."""
        raise NotImplementedError

    def database_path(self, root: Path) -> str:
        """Return the database path used by one fixture root."""
        raise NotImplementedError


HOTPATH_CODEC = cast(
    "_CodecModule",
    cast("object", import_module("e2e_registry.hotpath_codec")),
)
HOTPATH_READ = cast(
    "_StoreReadModule",
    cast("object", import_module("e2e_registry.hotpath_store_read")),
)
HOTPATH_SCHEMA = cast(
    "_StoreSchemaModule",
    cast("object", import_module("e2e_registry.hotpath_store_schema")),
)
HOTPATH_WRITE = cast(
    "_StoreWriteModule",
    cast("object", import_module("e2e_registry.hotpath_store_write")),
)
