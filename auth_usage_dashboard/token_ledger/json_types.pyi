# Copyright (c) 2026 PitchAI. All rights reserved.
# Type-only JSON and SQLite value aliases for the standalone token ledger package.

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type SqlValue = str | int | float | None
