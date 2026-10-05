#!/usr/bin/env bash
set -Eeuo pipefail

readonly EXPECTED_HOST="pitchai-dev"
readonly CONTAINER="codex-usage-dashboard"
readonly BROKER_CONTAINER="auth-token-server"
readonly BROKER_ENV="/etc/auth-token-server/auth-token-server.env"
readonly BROKER_ACCOUNTS="/srv/auth-token-server/data/accounts"
readonly DASHBOARD_DATA="/srv/codex-usage-dashboard"
readonly HISTORY_DB="${DASHBOARD_DATA}/usage-history.sqlite3"
readonly HISTORY_BACKUPS="${DASHBOARD_DATA}/backups"
readonly SUBSCRIPTIONS_FILE="${DASHBOARD_DATA}/codex-subscriptions.json"
readonly TOKEN_LEDGER_DB="${DASHBOARD_DATA}/token-ledger.sqlite3"
readonly TOKEN_LEDGER_LIB="/usr/local/lib/pitchai-token-ledger"
readonly TOKEN_LEDGER_NODES="master,jeff-dev,fsn1"
readonly PROD_PORT="8124"
readonly CANARY_PORT="18124"
readonly MOBILE_APP_ID_PREFIX="ZM6568G5FX"
readonly MOBILE_BUNDLE_ID="com.pitchai.codexstatus"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT
mobile_enrollment_enabled="${AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED:-0}"
subscriptions_source="${CODEX_SUBSCRIPTIONS_SOURCE:-/srv/codex-usage-dashboard-src/codex-subscriptions.json}"

if [[ "$(hostname -s)" != "${EXPECTED_HOST}" ]]; then
  printf 'Refusing deployment: expected host %s, found %s\n' "${EXPECTED_HOST}" "$(hostname -s)" >&2
  exit 1
fi
if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run this deployment as root.\n' >&2
  exit 1
fi
for command in docker curl python3 git; do
  command -v "${command}" >/dev/null || { printf 'Missing command: %s\n' "${command}" >&2; exit 1; }
done
[[ -r "${BROKER_ENV}" ]] || { printf 'Broker environment is not readable.\n' >&2; exit 1; }
[[ -d "${BROKER_ACCOUNTS}" ]] || { printf 'Broker account inventory is unavailable.\n' >&2; exit 1; }
install -d -m 700 -o root -g root "${DASHBOARD_DATA}"
install -d -m 700 -o root -g root "${HISTORY_BACKUPS}"
if [[ "${mobile_enrollment_enabled}" != "0" && "${mobile_enrollment_enabled}" != "1" ]]; then
  printf 'AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED must be 0 or 1.\n' >&2
  exit 1
fi
if [[ -e "${DASHBOARD_DATA}/mobile-app-attest.json" ]] &&
  [[ "$(stat -c '%a:%U:%G' "${DASHBOARD_DATA}/mobile-app-attest.json")" != "600:root:root" ]]; then
  printf 'Mobile App Attest registry permissions are not 600 root:root.\n' >&2
  exit 1
fi
[[ "$(stat -c '%a:%U:%G' "${BROKER_ENV}")" == "600:root:root" ]] || {
  printf 'Broker environment permissions are not 600 root:root.\n' >&2
  exit 1
}
[[ "$(docker inspect -f '{{.State.Running}}' "${BROKER_CONTAINER}" 2>/dev/null)" == "true" ]] || {
  printf 'Authoritative broker container is not running.\n' >&2
  exit 1
}
if ss -ltnH "sport = :${CANARY_PORT}" | grep -q .; then
  printf 'Canary port %s is already in use.\n' "${CANARY_PORT}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${BROKER_ENV}"
set +a
: "${AUTH_TOKEN_SERVER_ADMIN_TOKEN:?Broker admin token is absent}"
export AUTH_USAGE_BROKER_ADMIN_TOKEN="${AUTH_TOKEN_SERVER_ADMIN_TOKEN}"
unset AUTH_TOKEN_SERVER_CLIENT_TOKEN AUTH_TOKEN_SERVER_DATA_DIR

git_full_sha="$(git -C "${REPO_ROOT}" rev-parse --verify HEAD)"
git_sha="${git_full_sha:0:12}"
inventory_count="$(python3 - "${BROKER_ACCOUNTS}" <<'PY'
import pathlib
import sys

accounts = pathlib.Path(sys.argv[1])
count = sum(
    1
    for path in accounts.iterdir()
    if path.is_dir() and (path / "metadata.json").is_file()
)
if count < 1:
    raise RuntimeError("broker account inventory is empty")
print(count)
PY
)"
# Export only redacted owner status; login homes are never mounted in the dashboard.
install -d -m 755 /usr/local/lib/pitchai-codex-usage
install -m 644 "${REPO_ROOT}/auth_usage_dashboard/claude_accounts.py" /usr/local/lib/pitchai-codex-usage/claude_accounts.py
install -m 644 "${REPO_ROOT}/ops/claude-usage-export.service" /etc/systemd/system/claude-usage-export.service
install -m 644 "${REPO_ROOT}/ops/claude-usage-export.timer" /etc/systemd/system/claude-usage-export.timer
systemctl daemon-reload
systemctl enable --now claude-usage-export.timer >/dev/null
systemctl start claude-usage-export.service

# Fleet token ledger: master tails its own rollouts read-only and ingests worker
# batches (see ops/install_token_ledger_node.sh); the dashboard only reads it.
install -d -m 755 "${TOKEN_LEDGER_LIB}"
rm -rf "${TOKEN_LEDGER_LIB}/token_ledger.new"
cp -R "${REPO_ROOT}/auth_usage_dashboard/token_ledger" "${TOKEN_LEDGER_LIB}/token_ledger.new"
find "${TOKEN_LEDGER_LIB}/token_ledger.new" -name __pycache__ -prune -exec rm -rf {} +
printf '%s\n' "${git_full_sha}" > "${TOKEN_LEDGER_LIB}/token_ledger.new/VERSION"
chmod -R u=rwX,go=rX "${TOKEN_LEDGER_LIB}/token_ledger.new"
rm -rf "${TOKEN_LEDGER_LIB}/token_ledger.old"
if [[ -d "${TOKEN_LEDGER_LIB}/token_ledger" ]]; then
  mv "${TOKEN_LEDGER_LIB}/token_ledger" "${TOKEN_LEDGER_LIB}/token_ledger.old"
fi
mv "${TOKEN_LEDGER_LIB}/token_ledger.new" "${TOKEN_LEDGER_LIB}/token_ledger"
rm -rf "${TOKEN_LEDGER_LIB}/token_ledger.old"
install -m 644 "${REPO_ROOT}/ops/token-ledger-export.service" /etc/systemd/system/token-ledger-export.service
install -m 644 "${REPO_ROOT}/ops/token-ledger-export.timer" /etc/systemd/system/token-ledger-export.timer
systemctl daemon-reload
systemctl enable --now token-ledger-export.timer >/dev/null
systemctl start token-ledger-export.service || printf 'Token ledger first run failed; the timer retries.\n' >&2

# The curated subscription snapshot lives outside this public repository; the
# deployment only installs an already reviewed file and never invents states.
if [[ -f "${subscriptions_source}" ]]; then
  python3 - "${subscriptions_source}" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
accounts = payload["accounts"]
assert payload["schema_version"] == 1
assert accounts
assert all(
    row["email"] and row["access_status"] in {"active", "inactive", "unknown"}
    for row in accounts
)
PY
  install -m 600 -o root -g root "${subscriptions_source}" "${SUBSCRIPTIONS_FILE}"
else
  printf 'Subscription source %s is absent; states stay unavailable.\n' \
    "${subscriptions_source}" >&2
fi

image="${1:-codex-usage-dashboard:${git_sha}}"
if [[ $# -eq 0 ]]; then
  docker build --pull --tag "${image}" --file "${REPO_ROOT}/Dockerfile.auth-usage" "${REPO_ROOT}"
else
  docker image inspect "${image}" >/dev/null
fi

run_dashboard() {
  local name="$1"
  local port="$2"
  local restart_policy="$3"
  local probe_enabled="$4"
  local health_args=()
  local history_args=()
  if [[ "${port}" != "${PROD_PORT}" ]]; then
    health_args+=(--no-healthcheck)
    history_args+=("--tmpfs" "/dashboard-data:rw,nosuid,nodev,noexec,size=16m")
    if [[ -f "${DASHBOARD_DATA}/claude-accounts.json" ]]; then
      history_args+=(--mount "type=bind,src=${DASHBOARD_DATA}/claude-accounts.json,dst=/dashboard-data/claude-accounts.json,readonly")
    fi
    if [[ -f "${SUBSCRIPTIONS_FILE}" ]]; then
      history_args+=(--mount "type=bind,src=${SUBSCRIPTIONS_FILE},dst=/dashboard-data/codex-subscriptions.json,readonly")
    fi
    if [[ -f "${TOKEN_LEDGER_DB}" ]]; then
      history_args+=(--mount "type=bind,src=${TOKEN_LEDGER_DB},dst=/dashboard-data/token-ledger.sqlite3,readonly")
    fi
  else
    history_args+=(--mount "type=bind,src=${DASHBOARD_DATA},dst=/dashboard-data")
  fi
  docker run --detach \
    --name "${name}" \
    --restart "${restart_policy}" \
    --init \
    --network host \
    --user 0:0 \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 128 \
    --memory 384m \
    --cpus 1.0 \
    --mount "type=bind,src=${BROKER_ACCOUNTS},dst=/broker-data/accounts,readonly" \
    "${history_args[@]}" \
    --env AUTH_USAGE_BROKER_ADMIN_TOKEN \
    --env AUTH_USAGE_BROKER_DATA_DIR=/broker-data \
    --env AUTH_USAGE_BROKER_URL=http://127.0.0.1:38188 \
    --env AUTH_USAGE_BIND_HOST=127.0.0.1 \
    --env "AUTH_USAGE_BIND_PORT=${port}" \
    --env "AUTH_USAGE_SAFE_PROBE_ENABLED=${probe_enabled}" \
    --env AUTH_USAGE_SAFE_PROBE_INTERVAL_SECONDS=300 \
    --env AUTH_USAGE_ANALYTICS_PROBE_INTERVAL_SECONDS=900 \
    --env AUTH_USAGE_SNAPSHOT_REFRESH_SECONDS=15 \
    --env AUTH_USAGE_STALE_AFTER_SECONDS=600 \
    --env AUTH_USAGE_ANALYTICS_STALE_AFTER_SECONDS=1800 \
    --env AUTH_USAGE_HISTORY_FILE=/dashboard-data/usage-samples.json \
    --env AUTH_USAGE_HISTORY_RETENTION_DAYS=8 \
    --env AUTH_USAGE_HISTORY_SAMPLE_INTERVAL_SECONDS=300 \
    --env AUTH_USAGE_TIMESERIES_DB=/dashboard-data/usage-history.sqlite3 \
    --env AUTH_USAGE_TIMESERIES_SAMPLE_INTERVAL_SECONDS=300 \
    --env AUTH_USAGE_TIMESERIES_STARTUP_DELAY_SECONDS=30 \
    --env AUTH_USAGE_TOKEN_LEDGER_DB=/dashboard-data/token-ledger.sqlite3 \
    --env "AUTH_USAGE_TOKEN_LEDGER_NODES=${TOKEN_LEDGER_NODES}" \
    --env "AUTH_USAGE_COLLECTOR_VERSION=${git_full_sha}" \
    --env AUTH_USAGE_REQUIRE_PROXY_AUTH=1 \
    --env AUTH_USAGE_MOBILE_ENABLED=1 \
    --env "AUTH_USAGE_MOBILE_APP_ID_PREFIX=${MOBILE_APP_ID_PREFIX}" \
    --env "AUTH_USAGE_MOBILE_BUNDLE_ID=${MOBILE_BUNDLE_ID}" \
    --env AUTH_USAGE_MOBILE_APP_ATTEST_ENVIRONMENT=development \
    --env AUTH_USAGE_MOBILE_APP_ATTEST_REGISTRY_FILE=/dashboard-data/mobile-app-attest.json \
    --env "AUTH_USAGE_MOBILE_APP_ATTEST_ENROLLMENT_ENABLED=${mobile_enrollment_enabled}" \
    --env AUTH_USAGE_MOBILE_APP_ATTEST_MAX_KEYS=2 \
    --env AUTH_USAGE_MOBILE_BACKGROUND_REFRESH_SECONDS=900 \
    "${health_args[@]}" \
    "${image}" >/dev/null
}

check_history() {
  local name="$1"
  local expected_version="$2"
  local expected_accounts="$3"
  local attempts=180
  local output
  while (( attempts > 0 )); do
    if output="$(docker exec "${name}" python -m auth_usage_dashboard.history_cli \
      --database /dashboard-data/usage-history.sqlite3 status 2>/dev/null)" \
      && python3 -c '
import json
import sys

payload = json.load(sys.stdin)
expected_accounts = int(sys.argv[2])
assert payload["latest_collector_version"] == sys.argv[1]
assert payload["latest_source"] == "auth_usage_dashboard:redacted_broker_state"
assert payload["latest_batch_account_count"] == expected_accounts
assert payload["latest_batch_sample_count"] == expected_accounts
' "${expected_version}" "${expected_accounts}" <<<"${output}"; then
      break
    fi
    attempts=$((attempts - 1))
    sleep 0.5
  done
  (( attempts > 0 )) || return 1
  docker exec "${name}" python -m auth_usage_dashboard.history_cli \
    --database /dashboard-data/usage-history.sqlite3 summary --hours 24 >/dev/null
}

backup_history() {
  [[ -f "${HISTORY_DB}" ]] || return 0
  local backup_path="${HISTORY_BACKUPS}/usage-history-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
  python3 - "${HISTORY_DB}" "${backup_path}" <<'PY'
import os
import sqlite3
import sys

source_path, destination_path = sys.argv[1:]
source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30.0)
destination = sqlite3.connect(destination_path, timeout=30.0)
try:
    source.backup(destination)
    if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("history backup quick_check failed")
finally:
    destination.close()
    source.close()
os.chmod(destination_path, 0o600)
PY
}

check_dashboard() {
  local port="$1"
  local name="$2"
  # Production startup includes live broker probes and can legitimately take over 15s.
  local attempts=240
  local output
  local scheduling_output
  while (( attempts > 0 )); do
    if output="$(curl --fail --silent --show-error --max-time 3 \
      --header 'X-PitchAI-Email: deployment-check@pitchai.net' \
      "http://127.0.0.1:${port}/api/v1/capacity" 2>/dev/null)"; then
      if python3 "${REPO_ROOT}/auth_usage_dashboard/deployment_check.py" <<<"${output}"; then
        if scheduling_output="$(curl --fail --silent --show-error --max-time 3 \
          --header 'X-PitchAI-Email: deployment-check@pitchai.net' \
          "http://127.0.0.1:${port}/api/v1/scheduling-capacity" 2>/dev/null)" \
          && docker exec --interactive "${name}" python -m \
            auth_usage_dashboard.scheduling_capacity_check <<<"${scheduling_output}"; then
          local mobile_status
          mobile_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
            --max-time 3 \
            --header 'Content-Type: application/json' \
            --data '{"purpose":"capacity","key_id":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="}' \
            "http://127.0.0.1:${port}/api/v1/mobile/challenge" 2>/dev/null || true)"
          if [[ "${mobile_status}" == "401" ]]; then
            local claude_output
            if claude_output="$(curl --fail --silent --max-time 3 \
              --header 'X-PitchAI-Email: deployment-check@pitchai.net' \
              "http://127.0.0.1:${port}/api/v1/claude-accounts")" && \
              python3 -c 'import json,sys; p=json.load(sys.stdin); expected=json.load(open(sys.argv[1])); assert p["schema_version"] == 1 and not p["stale"] and not p["error"]; assert len(p["accounts"]) == len(expected["accounts"])' \
              "${DASHBOARD_DATA}/claude-accounts.json" <<<"${claude_output}"; then
              if check_token_usage "${port}" && check_subscriptions "${port}" "${name}"; then
                return 0
              fi
            fi
          fi
        fi
      fi
    fi
    attempts=$((attempts - 1))
    sleep 0.25
  done
  return 1
}

check_token_usage() {
  local port="$1"
  local output
  output="$(curl --fail --silent --max-time 10 \
    --header 'X-PitchAI-Email: deployment-check@pitchai.net' \
    "http://127.0.0.1:${port}/api/v1/token-usage?span=24h" 2>/dev/null)" || return 1
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
assert payload["schema_version"] == 1 and payload["range"] == "24h"
assert payload["dimensions"] is not None or payload["error"]
if payload["dimensions"] is not None:
    assert len(payload["buckets"]) == 24
    assert set(payload["dimensions"]) == {"provider", "model", "project"}
' <<<"${output}"
}

check_subscriptions() {
  local port="$1"
  local name="$2"
  if [[ ! -f "${SUBSCRIPTIONS_FILE}" ]]; then
    return 0
  fi
  local output
  if output="$(curl --fail --silent --show-error --max-time 3 \
    --header 'X-PitchAI-Email: deployment-check@pitchai.net' \
    "http://127.0.0.1:${port}/api/v1/subscription-accounts" 2>/dev/null)" \
    && docker exec --interactive "${name}" python -m \
      auth_usage_dashboard.subscription_accounts_check \
      /dashboard-data/codex-subscriptions.json <<<"${output}"; then
    return 0
  fi
  return 1
}

canary="${CONTAINER}-canary-$$"
backup="${CONTAINER}-rollback-$$"
cleanup() {
  docker rm --force "${canary}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_dashboard "${canary}" "${CANARY_PORT}" no 0
if ! check_dashboard "${CANARY_PORT}" "${canary}"; then
  printf 'Canary validation failed.\n' >&2
  docker logs --tail 30 "${canary}" >&2 || true
  exit 1
fi
if ! check_history "${canary}" "${git_full_sha}" "${inventory_count}"; then
  printf 'Canary time-series validation failed.\n' >&2
  docker logs --tail 30 "${canary}" >&2 || true
  exit 1
fi
docker rm --force "${canary}" >/dev/null

backup_history

had_previous=0
if docker container inspect "${CONTAINER}" >/dev/null 2>&1; then
  had_previous=1
  docker stop --time 20 "${CONTAINER}" >/dev/null
  docker rename "${CONTAINER}" "${backup}"
elif ss -ltnH "sport = :${PROD_PORT}" | grep -q .; then
  printf 'Production port %s is owned by an unexpected process.\n' "${PROD_PORT}" >&2
  exit 1
fi

rollback() {
  docker rm --force "${CONTAINER}" >/dev/null 2>&1 || true
  if (( had_previous == 1 )); then
    docker rename "${backup}" "${CONTAINER}" >/dev/null
    docker start "${CONTAINER}" >/dev/null
  fi
}

if ! run_dashboard "${CONTAINER}" "${PROD_PORT}" unless-stopped 1; then
  rollback
  printf 'Production container failed to start; previous container restored.\n' >&2
  exit 1
fi
if ! check_dashboard "${PROD_PORT}" "${CONTAINER}"; then
  docker logs --tail 30 "${CONTAINER}" >&2 || true
  rollback
  printf 'Production validation failed; previous container restored.\n' >&2
  exit 1
fi
if ! check_history "${CONTAINER}" "${git_full_sha}" "${inventory_count}"; then
  docker logs --tail 30 "${CONTAINER}" >&2 || true
  rollback
  printf 'Production time-series validation failed; previous container restored.\n' >&2
  exit 1
fi

if (( had_previous == 1 )); then
  docker rm "${backup}" >/dev/null
fi
unset AUTH_USAGE_BROKER_ADMIN_TOKEN AUTH_TOKEN_SERVER_ADMIN_TOKEN
printf 'Deployed %s on 127.0.0.1:%s with durable history %s\n' \
  "${image}" "${PROD_PORT}" "${HISTORY_DB}"
