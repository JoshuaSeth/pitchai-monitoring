#!/usr/bin/env bash
set -Eeuo pipefail

readonly EXPECTED_HOST="pitchai-dev"
readonly CONTAINER="codex-usage-dashboard"
readonly BROKER_CONTAINER="auth-token-server"
readonly BROKER_ENV="/etc/auth-token-server/auth-token-server.env"
readonly BROKER_ACCOUNTS="/srv/auth-token-server/data/accounts"
readonly DASHBOARD_DATA="/srv/codex-usage-dashboard"
readonly PROD_PORT="8124"
readonly CANARY_PORT="18124"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT

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

git_sha="$(git -C "${REPO_ROOT}" rev-parse --short=12 HEAD)"
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
    --env AUTH_USAGE_REQUIRE_PROXY_AUTH=1 \
    "${health_args[@]}" \
    "${image}" >/dev/null
}

check_dashboard() {
  local port="$1"
  local attempts=60
  local output
  while (( attempts > 0 )); do
    if output="$(curl --fail --silent --show-error --max-time 3 \
      --header 'X-PitchAI-Operator: deployment-check' \
      "http://127.0.0.1:${port}/api/v1/capacity" 2>/dev/null)"; then
      if python3 "${REPO_ROOT}/auth_usage_dashboard/deployment_check.py" <<<"${output}"; then
        return 0
      fi
    fi
    attempts=$((attempts - 1))
    sleep 0.25
  done
  return 1
}

canary="${CONTAINER}-canary-$$"
backup="${CONTAINER}-rollback-$$"
cleanup() {
  docker rm --force "${canary}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_dashboard "${canary}" "${CANARY_PORT}" no 0
if ! check_dashboard "${CANARY_PORT}"; then
  printf 'Canary validation failed.\n' >&2
  docker logs --tail 30 "${canary}" >&2 || true
  exit 1
fi
docker rm --force "${canary}" >/dev/null

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
if ! check_dashboard "${PROD_PORT}"; then
  docker logs --tail 30 "${CONTAINER}" >&2 || true
  rollback
  printf 'Production validation failed; previous container restored.\n' >&2
  exit 1
fi

if (( had_previous == 1 )); then
  docker rm "${backup}" >/dev/null
fi
unset AUTH_USAGE_BROKER_ADMIN_TOKEN AUTH_TOKEN_SERVER_ADMIN_TOKEN
printf 'Deployed %s on 127.0.0.1:%s\n' "${image}" "${PROD_PORT}"
