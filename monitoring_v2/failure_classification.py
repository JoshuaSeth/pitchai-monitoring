# Copyright (c) 2026 PitchAI. All rights reserved.
"""Classify sanitized database failures for actionable operations."""

_DIRECT_FAILURE_CLASSES = {
    "credential_missing",
    "credential_unreadable",
    "database_file_unreachable",
    "missing_schema_grant",
    "missing_relation_grant",
    "missing_table_or_materialized_view",
    "probe_configuration_invalid",
    "query_permission_failure",
}
_SQLSTATE_FAILURE_CLASSES = {
    "28P01": "invalid_or_revoked_password",
    "28000": "login_or_authentication_failure",
    "3F000": "missing_schema_grant",
    "42P01": "missing_table_or_materialized_view",
    "42704": "missing_table_or_materialized_view",
    "42501": "query_permission_failure",
    "57014": "timeout",
}
_EXCERPT_FAILURE_CLASSES = (
    (("timeout", "timed out", "deadline exceeded"), "timeout"),
    (("tunnel", "pgbouncer", "connection refused", "no route to host"), "database_or_pgbouncer_unreachable"),
    (
        ("password", "authentication", "not permitted to log in", "role is not permitted"),
        "login_or_authentication_failure",
    ),
    (("permission denied", "not authorized", "insufficient privilege"), "query_permission_failure"),
)


def classify_failure(*, kind: str, phase: str, sqlstate: str, excerpt: str) -> str:
    """Map a sanitized probe failure onto an actionable operator class.

    Returns:
        A stable, secret-free failure class for dashboard and alert routing.
    """
    if kind in _DIRECT_FAILURE_CLASSES:
        return kind
    exact_sqlstate_class = _SQLSTATE_FAILURE_CLASSES.get(sqlstate)
    if exact_sqlstate_class is not None:
        return exact_sqlstate_class
    if sqlstate.startswith("08") or sqlstate == "57P03":
        return "database_or_pgbouncer_unreachable"
    lowered = excerpt.lower()
    for terms, failure_class in _EXCERPT_FAILURE_CLASSES:
        if any(term in lowered for term in terms):
            return failure_class
    if kind == "database_query_error" or phase == "query":
        return "query_permission_failure"
    return "database_connection_failure"
