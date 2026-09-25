#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
readonly DEFAULT_PREFLIGHT="${SCRIPT_DIR}/auth_reset_guardian_notification_preflight.sh"
readonly TELEGRAM_HELPER_ROOT="/root/code/telegram_agent_server"
readonly RUNTIME_TMP="${TMPDIR:-/tmp}"
readonly RUNTIME_CACHE="${XDG_CACHE_HOME:-${RUNTIME_TMP}}"

preflight="${ASTRA_MODEL_WATCH_NOTIFICATION_PREFLIGHT:-${DEFAULT_PREFLIGHT}}"

if [[ "${1:-}" == "--preflight-only" ]]; then
  if [[ "$#" -ne 1 ]]; then
    printf 'Usage: %s --preflight-only\n' "$0" >&2
    exit 2
  fi
  exec "${preflight}"
fi

if [[ "$#" -ne 2 || "$1" != "--message" || -z "$2" ]]; then
  printf 'Usage: %s --message TEXT\n' "$0" >&2
  exit 2
fi
readonly message="$2"

"${preflight}" >/dev/null

exec /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 TMPDIR="${RUNTIME_TMP}" XDG_CACHE_HOME="${RUNTIME_CACHE}" \
  /usr/bin/python3 "${TELEGRAM_HELPER_ROOT}/main.py" send-message \
  --requester seth-ori \
  --message-class automation \
  --sensitive \
  --message "${message}"
