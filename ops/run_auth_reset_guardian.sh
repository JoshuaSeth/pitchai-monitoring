#!/usr/bin/env bash
set -Eeuo pipefail

readonly BROKER_ENV="/etc/auth-token-server/auth-token-server.env"
readonly INSTALL_ROOT="/opt/pitchai-auth-reset-guardian/current"

[[ -r "${BROKER_ENV}" ]] || {
  printf 'Reset guardian cannot read the broker environment.\n' >&2
  exit 1
}
[[ -d "${INSTALL_ROOT}/auth_reset_guardian" ]] || {
  printf 'Reset guardian release is not installed.\n' >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
source "${BROKER_ENV}"
set +a
: "${AUTH_TOKEN_SERVER_ADMIN_TOKEN:?Broker admin token is absent}"
export AUTH_RESET_GUARDIAN_BROKER_ADMIN_TOKEN="${AUTH_TOKEN_SERVER_ADMIN_TOKEN}"
export PYTHONPATH="${INSTALL_ROOT}"
unset AUTH_TOKEN_SERVER_ADMIN_TOKEN AUTH_TOKEN_SERVER_CLIENT_TOKEN AUTH_TOKEN_SERVER_DATA_DIR

exec /usr/bin/python3 -m auth_reset_guardian "$@"
