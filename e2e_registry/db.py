# Copyright (c) 2026 PitchAI. All rights reserved.
"""Stable database API for the E2E registry."""

from e2e_registry.db_claims import claim_due_runs
from e2e_registry.db_completion import complete_run
from e2e_registry.db_dispatch import (
    DispatchRunEntry,
    insert_dispatch_run,
    list_dispatch_runs,
)
from e2e_registry.db_identity import create_api_key, create_tenant, get_api_key_by_hash
from e2e_registry.db_queries import (
    get_run,
    get_test,
    get_test_config_internal,
    list_runs,
    list_tests,
)
from e2e_registry.db_schema import SCHEMA_VERSION, ensure_schema
from e2e_registry.db_status import status_summary
from e2e_registry.db_test_patch import patch_test
from e2e_registry.db_test_write import (
    NewTest,
    TestDisableChange,
    TestSourceUpdate,
    insert_test,
    set_test_disabled,
    trigger_run_now,
    update_test_source,
)
from e2e_registry.models import (
    AuthedTenant,
    ClaimedRun,
    CompletionOutcome,
    RunCompletion,
)

__all__ = [
    "SCHEMA_VERSION",
    "AuthedTenant",
    "ClaimedRun",
    "CompletionOutcome",
    "DispatchRunEntry",
    "NewTest",
    "RunCompletion",
    "TestDisableChange",
    "TestSourceUpdate",
    "claim_due_runs",
    "complete_run",
    "create_api_key",
    "create_tenant",
    "ensure_schema",
    "get_api_key_by_hash",
    "get_run",
    "get_test",
    "get_test_config_internal",
    "insert_dispatch_run",
    "insert_test",
    "list_dispatch_runs",
    "list_runs",
    "list_tests",
    "patch_test",
    "set_test_disabled",
    "status_summary",
    "trigger_run_now",
    "update_test_source",
]
