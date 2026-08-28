#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ROOT
readonly NOTIFIER="${ROOT}/ops/auth_reset_guardian_notifier.sh"
readonly FAIL_PREFLIGHT="${ROOT}/tests/fixtures/guardian-notifier-preflight-fail.sh"
readonly READY_PREFLIGHT="${ROOT}/tests/fixtures/guardian-notifier-preflight-success.sh"
readonly HELPER="${ROOT}/tests/fixtures/guardian-notifier-helper.sh"
readonly EXPECTED_RECEIPT='{"destination_ref":"seth-ori","policy":"personal-first","requester_key":"seth-ori","route_kind":"private","status":"sent"}'

set +e
failure_output="$({
  AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT="${FAIL_PREFLIGHT}" \
  AUTH_RESET_GUARDIAN_TELEGRAM_HELPER="${HELPER}" \
    "${NOTIFIER}" --message "safe message"
} 2>&1)"
failure_status=$?
set -e
if [[ "${failure_status}" -ne 1 || -n "${failure_output}" ]]; then
  printf 'Failed preflight did not stop cleanly before the helper (status=%s).\n' \
    "${failure_status}" >&2
  exit 1
fi

success_output="$(
  AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT="${READY_PREFLIGHT}" \
  AUTH_RESET_GUARDIAN_TELEGRAM_HELPER="${HELPER}" \
    "${NOTIFIER}" --message "safe message"
)"
if [[ "${success_output}" != "${EXPECTED_RECEIPT}" ]]; then
  printf 'Verified preflight did not preserve the private helper receipt.\n' >&2
  exit 1
fi

preflight_output="$(
  AUTH_RESET_GUARDIAN_NOTIFICATION_PREFLIGHT="${READY_PREFLIGHT}" \
    "${NOTIFIER}" --preflight-only
)"
if [[ "${preflight_output}" != *'"status":"ready"'* ]]; then
  printf 'Preflight-only mode did not return a ready receipt.\n' >&2
  exit 1
fi

printf 'auth reset guardian notifier boundary: ok\n'
