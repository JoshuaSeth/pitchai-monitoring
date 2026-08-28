# Copyright (c) 2026 PitchAI. All rights reserved.
"""Validated scalar values and probe rules for database monitoring."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple, cast

from .json_types import bool_value, int_value, text_value, value_list
from .models import ProbeRule

if TYPE_CHECKING:
    from .json_types import JsonObject, JsonValue
    from .models import ConnectionMode

_CONNECTION_MODES = {"engine", "sqlalchemy_url", "psycopg_url", "asyncpg_url", "sqlite"}
_SYNC_DRIVERS = {"psycopg", "psycopg2"}


class DatabaseDependencyConfigurationError(ValueError):
    """The database dependency policy is incomplete or invalid."""


class _ProbeSources(NamedTuple):
    """Connection-source fields that must be validated together."""

    prefix: str
    mode: ConnectionMode
    engine_attr: str | None
    engine_callable: bool
    environment_keys: tuple[str, ...]
    file_environment_keys: tuple[str, ...]
    default_credential_path: str | None
    default_sqlite_path: str | None
    sync_driver: str | None


def required_text(value: JsonValue | object, *, field: str) -> str:
    """Return one required, non-empty configuration string.

    Returns:
        The normalized configuration string.

    Raises:
        DatabaseDependencyConfigurationError: If the value is empty or not text.
    """
    text = text_value(value).strip()
    if not text:
        message = f"database dependency setting {field} must be non-empty text"
        raise DatabaseDependencyConfigurationError(message)
    return text


def optional_text(value: JsonValue | object) -> str | None:
    """Return normalized optional configuration text.

    Returns:
        The normalized string, or ``None`` when empty.
    """
    text = text_value(value).strip()
    return text or None


def required_boolean(value: JsonValue | object, *, field: str) -> bool:
    """Return one required configuration boolean.

    Returns:
        The validated boolean.

    Raises:
        DatabaseDependencyConfigurationError: If the value is not a boolean.
    """
    boolean = bool_value(value)
    if boolean is None:
        message = f"database dependency setting {field} must be a boolean"
        raise DatabaseDependencyConfigurationError(message)
    return boolean


def required_positive_integer(value: JsonValue | object, *, field: str) -> int:
    """Return one required positive configuration integer.

    Returns:
        The validated positive integer.

    Raises:
        DatabaseDependencyConfigurationError: If the value is not positive.
    """
    number = int_value(value)
    if number is None or number < 1:
        message = f"database dependency setting {field} must be a positive integer"
        raise DatabaseDependencyConfigurationError(message)
    return number


def text_tuple(value: JsonValue | object, *, field: str) -> tuple[str, ...]:
    """Return a normalized tuple of required strings.

    Returns:
        The validated strings in declared order.
    """
    return tuple(required_text(item, field=f"{field}[{index}]") for index, item in enumerate(value_list(value)))


def _connection_mode(value: JsonValue | object, *, field: str) -> ConnectionMode:
    mode = required_text(value, field=field)
    if mode not in _CONNECTION_MODES:
        message = f"database dependency setting {field} has unsupported mode {mode}"
        raise DatabaseDependencyConfigurationError(message)
    return cast("ConnectionMode", mode)


def _parse_probe_sources(raw: JsonObject, *, prefix: str) -> _ProbeSources:
    sources = _ProbeSources(
        prefix=prefix,
        mode=_connection_mode(raw.get("connection_mode"), field=f"{prefix}.connection_mode"),
        engine_attr=optional_text(raw.get("engine_attr")),
        engine_callable=required_boolean(raw.get("engine_callable"), field=f"{prefix}.engine_callable"),
        environment_keys=text_tuple(raw.get("environment_keys"), field=f"{prefix}.environment_keys"),
        file_environment_keys=text_tuple(
            raw.get("file_environment_keys"),
            field=f"{prefix}.file_environment_keys",
        ),
        default_credential_path=optional_text(raw.get("default_credential_path")),
        default_sqlite_path=optional_text(raw.get("default_sqlite_path")),
        sync_driver=optional_text(raw.get("sync_driver")),
    )
    _validate_probe_sources(sources)
    return sources


def parse_probe_rule(raw: JsonObject, *, index: int) -> ProbeRule:
    """Parse and cross-validate one ordered container probe rule.

    Returns:
        The validated probe rule.

    Raises:
        DatabaseDependencyConfigurationError: If the rule is internally inconsistent.
    """
    prefix = f"database_dependencies.rules[{index}]"
    sources = _parse_probe_sources(raw, prefix=prefix)
    critical = required_boolean(raw.get("critical"), field=f"{prefix}.critical")
    telegram_enabled = required_boolean(raw.get("telegram_enabled"), field=f"{prefix}.telegram_enabled")
    routing_policy_id = optional_text(raw.get("routing_policy_id"))
    traffic_slot = optional_text(raw.get("traffic_slot"))
    environment = required_text(raw.get("environment"), field=f"{prefix}.environment")
    if (routing_policy_id is None) != (traffic_slot is None):
        message = f"{prefix}.routing_policy_id and traffic_slot must be configured together"
        raise DatabaseDependencyConfigurationError(message)
    if critical and environment != "production":
        message = f"critical database dependency rule {prefix} must target production"
        raise DatabaseDependencyConfigurationError(message)
    if telegram_enabled and (not critical or environment != "production"):
        message = f"Telegram-enabled database dependency rule {prefix} must be critical production"
        raise DatabaseDependencyConfigurationError(message)
    return ProbeRule(
        rule_id=required_text(raw.get("id"), field=f"{prefix}.id"),
        container_pattern=re.compile(required_text(raw.get("container_pattern"), field=f"{prefix}.container_pattern")),
        app_name=required_text(raw.get("app_name"), field=f"{prefix}.app_name"),
        owner_project=required_text(raw.get("owner_project"), field=f"{prefix}.owner_project"),
        database_label=required_text(raw.get("database_label"), field=f"{prefix}.database_label"),
        environment=environment,
        critical=critical,
        telegram_enabled=telegram_enabled,
        required_group=optional_text(raw.get("required_group")),
        domains=text_tuple(raw.get("domains"), field=f"{prefix}.domains"),
        likely_fix_path=required_text(raw.get("likely_fix_path"), field=f"{prefix}.likely_fix_path"),
        connection_mode=sources.mode,
        environment_keys=sources.environment_keys,
        file_environment_keys=sources.file_environment_keys,
        default_credential_path=sources.default_credential_path,
        default_sqlite_path=sources.default_sqlite_path,
        engine_attr=sources.engine_attr,
        engine_callable=sources.engine_callable,
        sync_driver=sources.sync_driver,
        relation_checks=text_tuple(raw.get("relation_checks"), field=f"{prefix}.relation_checks"),
        schema_checks=text_tuple(raw.get("schema_checks"), field=f"{prefix}.schema_checks"),
        routing_policy_id=routing_policy_id,
        traffic_slot=traffic_slot,
        alert_group=required_text(raw.get("alert_group"), field=f"{prefix}.alert_group"),
    )


def _validate_probe_sources(sources: _ProbeSources) -> None:
    prefix = sources.prefix
    if sources.mode == "engine" and sources.engine_attr is None:
        message = f"{prefix}.engine_attr is required for engine mode"
        raise DatabaseDependencyConfigurationError(message)
    if sources.mode != "engine" and sources.engine_attr is not None:
        message = f"{prefix}.engine_attr is only valid for engine mode"
        raise DatabaseDependencyConfigurationError(message)
    has_runtime_source = bool(
        sources.environment_keys
        or sources.file_environment_keys
        or sources.default_credential_path
        or sources.default_sqlite_path,
    )
    if sources.mode != "engine" and not has_runtime_source:
        message = f"{prefix} must define a runtime credential or SQLite path source"
        raise DatabaseDependencyConfigurationError(message)
    if sources.mode == "sqlite" and sources.default_credential_path is not None:
        message = f"{prefix}.default_credential_path is invalid for sqlite mode"
        raise DatabaseDependencyConfigurationError(message)
    if sources.mode != "sqlite" and sources.default_sqlite_path is not None:
        message = f"{prefix}.default_sqlite_path is only valid for sqlite mode"
        raise DatabaseDependencyConfigurationError(message)
    invalid_sync_driver = sources.mode not in {"psycopg_url", "sqlalchemy_url"}
    invalid_sync_driver = invalid_sync_driver or sources.sync_driver not in _SYNC_DRIVERS
    if sources.sync_driver is not None and invalid_sync_driver:
        message = f"{prefix}.sync_driver must be psycopg or psycopg2 for a synchronous PostgreSQL mode"
        raise DatabaseDependencyConfigurationError(message)
