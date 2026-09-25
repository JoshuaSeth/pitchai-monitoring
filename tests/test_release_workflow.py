# Copyright (c) 2026 PitchAI. All rights reserved.
"""Release-provenance checks for the production workflow."""

from pathlib import Path

from domain_checks.testing import verify

_EXPECTED_EXACT_SHA_REFERENCE_COUNT = 2
_EXPECTED_DEPLOY_DIR_VALIDATION_COUNT = 2
_EXPECTED_NO_NEW_PRIVILEGES_COUNT = 4
_EXPECTED_REMOTE_TIP_CHECK_COUNT = 2
_DOWNLOAD_ARTIFACT_SHA = "d3f86a106a0bac45b974a628896c90dbdf5c8093"


def test_production_workflow_deploys_only_the_validated_main_sha() -> None:
    """Verify deployment stays bound to the successful strict-gate main commit."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8",
    )

    verify('workflows: ["Python strict gate"]' in workflow)
    verify("workflow_dispatch" not in workflow)
    verify("github.event.workflow_run.conclusion == 'success'" in workflow)
    verify("github.event.workflow_run.event == 'push'" in workflow)
    verify("github.event.workflow_run.head_branch == 'main'" in workflow)
    verify("github.event.workflow_run.head_repository.full_name == github.repository" in workflow)
    exact_sha_references = workflow.count("ref: ${{ github.event.workflow_run.head_sha }}")
    verify(
        exact_sha_references == _EXPECTED_EXACT_SHA_REFERENCE_COUNT,
    )
    verify("VALIDATED_SHA: ${{ github.event.workflow_run.head_sha }}" in workflow)
    verify('test "$(git rev-parse HEAD)" = "$VALIDATED_SHA"' in workflow)
    verify("git fetch --no-tags --depth=1 origin refs/heads/main" in workflow)
    verify('test "$(git rev-parse FETCH_HEAD)" = "$VALIDATED_SHA"' in workflow)
    remote_tip_check = 'remote_main_sha="$(git ls-remote origin refs/heads/main'
    verify(workflow.count(remote_tip_check) == _EXPECTED_REMOTE_TIP_CHECK_COUNT)
    verify('if [[ "$remote_main_sha" != "$VALIDATED_SHA" ]]' in workflow)
    verify('git checkout --detach "$VALIDATED_SHA"' in workflow)
    verify('IMAGE_SHA="service-monitoring:${VALIDATED_SHA}"' in workflow)
    verify("environment: production" in workflow)
    verify("trap 'on_deploy_exit \"$?\"' EXIT" in workflow)
    verify('rm -rf -- "$DEPLOY_DIR"' in workflow)
    verify('RUN_ID="${{ github.run_id }}"' in workflow)
    verify('RUN_ATTEMPT="${{ github.run_attempt }}"' in workflow)
    verify('! "$RUN_ID" =~ ^[1-9][0-9]*$' in workflow)
    verify('! "$RUN_ATTEMPT" =~ ^[1-9][0-9]*$' in workflow)
    verify(
        workflow.count(
            '! "$DEPLOY_DIR" =~ ^/tmp/service-monitoring-deploy-[1-9][0-9]*-[1-9][0-9]*$',
        )
        == _EXPECTED_DEPLOY_DIR_VALIDATION_COUNT,
    )
    verify('! "$ROLLBACK_SUFFIX" =~ ^rollback-[1-9][0-9]*-[1-9][0-9]*$' in workflow)
    verify("readonly DEPLOY_DIR ROLLBACK_SUFFIX" in workflow)
    verify('mkdir -m 700 -- "$DEPLOY_DIR"' in workflow)

    rollback_trap = workflow.index("trap 'on_deploy_exit \"$?\"' EXIT")
    workspace_creation = workflow.index('mkdir -m 700 -- "$DEPLOY_DIR"')
    image_build = workflow.index('docker build -t "$IMAGE_SHA" .')
    e2e_config_ready = workflow.index('E2E_MONITOR_TOKEN="$(awk -F=')
    afas_config_ready = workflow.index('AFASASK_DEMO_PASSWORD="$(awk -F=')
    second_remote_tip_check = workflow.index(remote_tip_check, workflow.index(remote_tip_check) + 1)
    current_release_preservation = workflow.index("preserve_current_release\n")
    first_candidate_start = workflow.index(
        'docker run -d \\\n              --name "$REGISTRY_NAME"',
    )
    verify(workspace_creation < rollback_trap < image_build)
    verify(image_build < e2e_config_ready < afas_config_ready < second_remote_tip_check)
    verify(second_remote_tip_check < current_release_preservation < first_candidate_start)


def test_production_runtime_preflight_is_fail_closed() -> None:
    """Verify runtime credentials and images are validated before release commit."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8",
    )

    verify("PITCHAI_MONITORING_EVENT_BUS_URL" in workflow)
    verify("PITCHAI_MONITORING_EVENT_BUS_SECRET" in workflow)
    verify("PITCHAI_MONITORING_DEPLOYMENT_SHA" in workflow)
    verify("docker volume create e2e-runner-leases" in workflow)
    verify("-v e2e-runner-leases:/uid-leases" in workflow)
    verify('-e E2E_SANDBOX_UID_LEASE_DIR="/uid-leases/locks"' in workflow)
    no_new_privileges_count = workflow.count("--security-opt no-new-privileges:true")
    verify(no_new_privileges_count == _EXPECTED_NO_NEW_PRIVILEGES_COUNT)
    verify('[[ "${#EVENT_BUS_SECRET}" -lt 32 ]]' in workflow)
    verify("umask 077" in workflow)
    verify('if [[ -L "$SECRETS_DIR" || ! -d "$SECRETS_DIR" ]]' in workflow)
    verify('chmod 700 "$SECRETS_DIR"' in workflow)
    verify('if [[ -L "$E2E_ENV_FILE" || ! -f "$E2E_ENV_FILE" ]]' in workflow)
    verify(
        'if [[ -L "$AFASASK_MONITOR_ENV_FILE" || ! -f "$AFASASK_MONITOR_ENV_FILE" ]]'
        in workflow,
    )
    verify('chmod 600 "$E2E_ENV_FILE"\n' in workflow)
    verify('chmod 600 "$AFASASK_MONITOR_ENV_FILE"\n' in workflow)
    verify('chmod 600 "$E2E_ENV_FILE" || true' not in workflow)
    verify('chmod 600 "$AFASASK_MONITOR_ENV_FILE" || true' not in workflow)
    verify("for stability_check in 1 2" in workflow)
    verify("{{.State.Restarting}}" in workflow)
    verify("{{.RestartCount}}" in workflow)
    verify("load_event_bus_config() is not None" in workflow)
    candidate_image_lookup = (
        'candidate_image_id="$(docker image inspect "$IMAGE_SHA" '
        '--format \'{{.Id}}\')"'
    )
    verify(candidate_image_lookup in workflow)
    verify('for name in "${CONTAINER_NAMES[@]}"' in workflow)
    verify('running_image_id="$(docker inspect "$name" --format \'{{.Image}}\')"' in workflow)
    verify('if [[ "$running_image_id" != "$candidate_image_id" ]]' in workflow)

    umask = workflow.index("umask 077")
    first_token_generation = workflow.index('admin="$(python3 -c')
    e2e_shape_check = workflow.index('if [[ -L "$E2E_ENV_FILE"')
    afas_shape_check = workflow.index('if [[ -L "$AFASASK_MONITOR_ENV_FILE"')
    current_release_preservation = workflow.index("preserve_current_release\n")
    verify(umask < first_token_generation < e2e_shape_check < afas_shape_check)
    verify(afas_shape_check < current_release_preservation)


def test_production_cutover_preserves_and_restores_the_previous_release() -> None:
    """Verify failed cutovers restore containers and the mutable latest tag."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8",
    )

    verify('CONTAINER_NAMES=("$REGISTRY_NAME" "$RUNNER_NAME" "$APP_NAME")' in workflow)
    verify("PRESERVED_NAMES=()" in workflow)
    verify("deployment_committed=false" in workflow)
    verify("cutover_started=false" in workflow)
    verify("rollback_active=false" in workflow)
    verify("latest_tag_changed=false" in workflow)
    verify("preserve_current_release()" in workflow)
    verify("restore_previous_release()" in workflow)
    verify("on_deploy_exit()" in workflow)
    verify('local original_status="$1"' in workflow)
    verify("original_status=$?" not in workflow)
    verify('docker rm --force "$name" || restore_failed=1' in workflow)
    verify('docker rename "$rollback_name" "$name" || restore_failed=1' in workflow)
    verify('docker start "$name" || restore_failed=1' in workflow)
    verify('docker tag "$previous_latest_image" "$IMAGE_LATEST" || restore_failed=1' in workflow)
    verify('docker image rm "$IMAGE_LATEST" || restore_failed=1' in workflow)
    verify('PRESERVED_NAMES+=("$OLD_NAME")' in workflow)
    verify("monitoring-system | monitoring-system:* | service-monitoring" in workflow)
    verify('if [[ "$existing_count" -ne 0 &&' in workflow)
    verify("cutover_started=true" in workflow)
    verify("latest_tag_changed=true" in workflow)
    verify("deployment_committed=true" in workflow)
    verify('stop_rm_if_exists "$APP_NAME"' not in workflow)

    preserve_call = workflow.index("preserve_current_release\n")
    cutover_start = workflow.index("cutover_started=true", preserve_call)
    candidate_start = workflow.index('docker run -d \\\n              --name "$REGISTRY_NAME"')
    stability_check = workflow.index('docker exec "$APP_NAME" python -c')
    container_image_check = workflow.index('candidate_image_id="$(docker image inspect')
    latest_tag = workflow.index('docker tag "$IMAGE_SHA" "$IMAGE_LATEST"')
    deployment_commit = workflow.index("deployment_committed=true")
    preserved_cleanup = workflow.index('for name in "${PRESERVED_NAMES[@]}"', deployment_commit)
    verify(preserve_call < cutover_start < candidate_start)
    verify(
        candidate_start
        < stability_check
        < container_image_check
        < latest_tag
        < deployment_commit
        < preserved_cleanup,
    )


def test_release_selector_uses_the_last_successful_deployment_range() -> None:
    """Verify canceled or superseded runs cannot hide undeployed runtime changes."""
    repository_root = Path(__file__).parents[1]
    workflow = (repository_root / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8",
    )
    strict_workflow = (repository_root / ".github" / "workflows" / "python-strict.yml").read_text(
        encoding="utf-8",
    )

    verify("actions: read" in workflow)
    verify(f"actions/download-artifact@{_DOWNLOAD_ARTIFACT_SHA}" in workflow)
    verify("github-token: ${{ github.token }}" in workflow)
    verify("run-id: ${{ github.event.workflow_run.id }}" in workflow)
    verify("github.event.workflow_run.run_attempt" in workflow)
    verify("fetch-depth: 0" in workflow)
    verify("service-monitoring-production-release" in workflow)
    verify("actions/artifacts?name=$RELEASE_MARKER_NAME&per_page=100" in workflow)
    successful_workflow_run = (
        '.event == "workflow_run" and .status == "completed" '
        'and .conclusion == "success"'
    )
    verify(successful_workflow_run in workflow)
    verify('.path == ".github/workflows/ci-cd.yaml"' in workflow)
    verify('mapfile -t marker_members < <(unzip -Z1 "$marker_zip")' in workflow)
    verify('unzip -p "$marker_zip" production-release.json >"$marker_path"' in workflow)
    verify('unzip -qq "$marker_zip"' not in workflow)
    verify('last_deployed_sha="$(jq --raw-output' in workflow)
    verify('marker_strict_run_id="$(jq --raw-output' in workflow)
    verify('.path == ".github/workflows/python-strict.yml" and .head_branch == "main"' in workflow)
    verify(".head_sha == $validated_sha and .repository.full_name == $repository" in workflow)
    verify('git diff --name-only --no-renames -z "$last_deployed_sha" "$VALIDATED_SHA"' in workflow)
    verify('git merge-base --is-ancestor "$last_deployed_sha" "$VALIDATED_SHA"' in workflow)
    verify('git merge-base --is-ancestor "$before_sha" "$VALIDATED_SHA"' in workflow)
    verify("${VALIDATED_SHA}^" not in workflow)
    verify("deployment is required" in workflow)
    verify("Record the exact successful production release" in workflow)
    verify("Preserve the exact successful production release" in workflow)
    verify("retention-days: 90" in workflow)

    remote_stability_check = workflow.index('docker exec "$APP_NAME" python -c')
    marker_creation = workflow.index("Record the exact successful production release")
    marker_upload = workflow.index("Preserve the exact successful production release")
    verify(remote_stability_check < marker_creation < marker_upload)

    verify("BEFORE_SHA: ${{ github.event.before }}" in strict_workflow)
    verify("AFTER_SHA: ${{ github.sha }}" in strict_workflow)
    verify("github.event_name == 'push' && github.ref == 'refs/heads/main'" in strict_workflow)
    provenance_artifact = (
        "python-release-provenance-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    verify(provenance_artifact in strict_workflow)
    verify("before: $before, after: $after" in strict_workflow)
    capture_index = strict_workflow.index("Capture the original main push range")
    first_project_execution = strict_workflow.index("astral-sh/setup-uv")
    verify(capture_index < first_project_execution)


def test_release_selector_preserves_the_migrated_non_runtime_exclusions() -> None:
    """Verify only the explicitly migrated documentation and quality paths may skip deploy."""
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci-cd.yaml").read_text(
        encoding="utf-8",
    )
    non_runtime_selector = (
        ".github/workflows/* | .python-version | docs/* | QUALITY.md | pyproject.toml | "
        "quality/* | README.md | uv.lock)"
    )
    verify(non_runtime_selector in workflow)
