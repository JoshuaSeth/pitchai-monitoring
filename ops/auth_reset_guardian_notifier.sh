#!/usr/bin/env bash
set -Eeuo pipefail

readonly DEFAULT_PREFLIGHT="/usr/local/sbin/pitchai-auth-reset-guardian-notification-preflight"
readonly TELEGRAM_HELPER_ROOT="/root/code/telegram_agent_server"

preflight="${AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT:-${DEFAULT_PREFLIGHT}}"

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

if [[ -n "${AUTH_RESET_GUARDIAN_TELEGRAM_HELPER:-}" ]]; then
  helper_command=("${AUTH_RESET_GUARDIAN_TELEGRAM_HELPER}")
else
  helper_command=(/usr/bin/python3 "${TELEGRAM_HELPER_ROOT}/main.py")
fi

exec /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin LANG=C.UTF-8 \
  "${helper_command[@]}" send-message \
  --requester seth-ori \
  --message-class automation \
  --sensitive \
  --message "${message}"
