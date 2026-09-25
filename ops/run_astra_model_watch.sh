#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPO_ROOT
readonly ACCOUNTS_DIR="/srv/auth-token-server/data/accounts"
readonly STATE_ROOT="/mnt/pitchai-dev-data/monitoring/auth-broker-astra-model-watch"
readonly SCRATCH_ROOT="/mnt/pitchai-dev-data/scratch/auth-broker-astra-model-watch"
readonly TMP_ROOT="${SCRATCH_ROOT}/runtime-tmp"
readonly CACHE_ROOT="${SCRATCH_ROOT}/runtime-cache"
readonly ALERT_STATE="${STATE_ROOT}/alert-state.json"
readonly NOTIFIER="${SCRIPT_DIR}/astra_model_watch_notifier.sh"
# OpenAI's 2026-09-04 Codex 0.153.1 release backported the GPT-6-Astra
# model-catalog entry. Older client_version values return a valid but stale
# catalog that omits Astra, so the monitor must not query below this version.
readonly CLIENT_VERSION="0.153.1"

declare -a MODE_ARGS
if [[ "$#" -eq 0 ]]; then
  START_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  readonly START_STAMP
  LOG_PATH="${STATE_ROOT}/astra-model-watch-${START_STAMP}.jsonl"
  MODE_ARGS=(
    --interval-seconds 300
    --duration-seconds 7200
    --heartbeat-seconds 45
  )
elif [[ "$#" -eq 1 && "$1" == "--once" ]]; then
  LOG_PATH="${STATE_ROOT}/durable-astra-model-watch.jsonl"
  MODE_ARGS=(--once)
else
  printf 'Usage: %s [--once]\n' "$0" >&2
  exit 2
fi
readonly LOG_PATH
readonly -a MODE_ARGS

install -d -m 0700 -o root -g root \
  "${STATE_ROOT}" \
  "${SCRATCH_ROOT}" \
  "${TMP_ROOT}" \
  "${CACHE_ROOT}"

printf 'ASTRA_WATCH_LOG=%s\n' "${LOG_PATH}"
cd -- "${REPO_ROOT}"
exec /usr/bin/env \
  PYTHONDONTWRITEBYTECODE=1 \
  TMPDIR="${TMP_ROOT}" \
  XDG_CACHE_HOME="${CACHE_ROOT}" \
  PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  /usr/bin/python3 -m astra_model_watch \
  --accounts-dir "${ACCOUNTS_DIR}" \
  --log-path "${LOG_PATH}" \
  --alert-state-path "${ALERT_STATE}" \
  --notify-command "${NOTIFIER}" \
  --client-version "${CLIENT_VERSION}" \
  --request-timeout-seconds 20 \
  "${MODE_ARGS[@]}"
