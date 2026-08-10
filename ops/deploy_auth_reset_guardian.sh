#!/usr/bin/env bash
set -Eeuo pipefail

readonly EXPECTED_HOST="pitchai-dev"
readonly INSTALL_BASE="/opt/pitchai-auth-reset-guardian"
readonly RELEASES_DIR="${INSTALL_BASE}/releases"
readonly CURRENT_LINK="${INSTALL_BASE}/current"
readonly DATA_DIR="/var/lib/pitchai-auth-reset-guardian"
readonly AUDIT_DB="${DATA_DIR}/audit.sqlite3"
readonly RUNNER="/usr/local/sbin/pitchai-auth-reset-guardian"
readonly ENV_FILE="/etc/pitchai-auth-reset-guardian.env"
readonly SERVICE_FILE="/etc/systemd/system/pitchai-auth-reset-guardian.service"
readonly TIMER_FILE="/etc/systemd/system/pitchai-auth-reset-guardian.timer"
readonly BROKER_ENV="/etc/auth-token-server/auth-token-server.env"
readonly TELEGRAM_REPO="/root/code/telegram_agent_server"
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
for command in git python3 systemctl sha256sum curl; do
  command -v "${command}" >/dev/null || {
    printf 'Missing deployment command: %s\n' "${command}" >&2
    exit 1
  }
done
[[ -r "${BROKER_ENV}" ]] || { printf 'Broker environment is not readable.\n' >&2; exit 1; }
[[ "$(stat -c '%a:%U:%G' "${BROKER_ENV}")" == "600:root:root" ]] || {
  printf 'Broker environment permissions must be 600 root:root.\n' >&2
  exit 1
}
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:38188/healthz >/dev/null
[[ -r "${TELEGRAM_REPO}/main.py" ]] || { printf 'Canonical Telegram helper is unavailable.\n' >&2; exit 1; }
(
  cd "${TELEGRAM_REPO}"
  /usr/bin/env -i HOME=/root PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 - <<'PY'
from telegram_agent_server.config import load_settings
settings = load_settings()
if "seth-ori" not in settings.route_registry.private:
    raise SystemExit("Seth requester-private Telegram route is unavailable")
if not settings.bot_token:
    raise SystemExit("Telegram bot configuration is unavailable")
PY
)

mapfile -d '' -t source_files < <(
  cd "${REPO_ROOT}"
  {
    find auth_reset_guardian -type f -name '*.py' -print0
    printf '%s\0' \
      fixtures/auth-reset-guardian-expiring.json \
      docs/auth-reset-guardian.md \
      ops/run_auth_reset_guardian.sh \
      ops/deploy_auth_reset_guardian.sh \
      ops/auth-reset-guardian.env \
      ops/systemd/pitchai-auth-reset-guardian.service \
      ops/systemd/pitchai-auth-reset-guardian.timer
  } | LC_ALL=C sort -z
)
for relative_path in "${source_files[@]}"; do
  if ! committed_blob="$(
    git -C "${REPO_ROOT}" rev-parse --verify "HEAD:${relative_path}" 2>/dev/null
  )"; then
    printf 'Refusing deployment: %s is not present in HEAD.\n' "${relative_path}" >&2
    exit 1
  fi
  working_blob="$(git -C "${REPO_ROOT}" hash-object -- "${relative_path}")"
  if [[ "${working_blob}" != "${committed_blob}" ]]; then
    printf 'Refusing deployment: %s differs from HEAD.\n' "${relative_path}" >&2
    exit 1
  fi
done
source_hash="$(
  cd "${REPO_ROOT}"
  printf '%s\0' "${source_files[@]}" \
    | xargs -0 sha256sum \
    | sha256sum \
    | cut -d' ' -f1
)"
git_sha="$(git -C "${REPO_ROOT}" rev-parse --verify HEAD)"
release_id="${git_sha:0:12}-${source_hash:0:12}"
release_dir="${RELEASES_DIR}/${release_id}"

install -d -m 755 -o root -g root "${RELEASES_DIR}"
install -d -m 700 -o root -g root "${DATA_DIR}"
if [[ ! -d "${release_dir}" ]]; then
  staging_dir="$(mktemp -d "${RELEASES_DIR}/.staging-${release_id}.XXXXXX")"
  cleanup_staging() {
    if [[ -n "${staging_dir:-}" && -d "${staging_dir}" ]]; then
      rm -rf -- "${staging_dir}"
    fi
  }
  trap cleanup_staging EXIT
  install -d -m 755 "${staging_dir}/auth_reset_guardian" "${staging_dir}/fixtures" "${staging_dir}/docs"
  install -m 644 "${REPO_ROOT}"/auth_reset_guardian/*.py "${staging_dir}/auth_reset_guardian/"
  install -m 644 "${REPO_ROOT}/fixtures/auth-reset-guardian-expiring.json" "${staging_dir}/fixtures/"
  install -m 644 "${REPO_ROOT}/docs/auth-reset-guardian.md" "${staging_dir}/docs/"
  printf '{"git_sha":"%s","source_sha256":"%s"}\n' "${git_sha}" "${source_hash}" >"${staging_dir}/release.json"
  chmod 644 "${staging_dir}/release.json"
  mv "${staging_dir}" "${release_dir}"
  staging_dir=""
  trap - EXIT
fi

previous_target="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
temporary_link="${INSTALL_BASE}/.current-${release_id}-$$"
ln -s "${release_dir}" "${temporary_link}"
mv -Tf "${temporary_link}" "${CURRENT_LINK}"

install -m 755 -o root -g root "${REPO_ROOT}/ops/run_auth_reset_guardian.sh" "${RUNNER}"
install -m 600 -o root -g root "${REPO_ROOT}/ops/auth-reset-guardian.env" "${ENV_FILE}"
install -m 644 -o root -g root \
  "${REPO_ROOT}/ops/systemd/pitchai-auth-reset-guardian.service" "${SERVICE_FILE}"
install -m 644 -o root -g root \
  "${REPO_ROOT}/ops/systemd/pitchai-auth-reset-guardian.timer" "${TIMER_FILE}"
systemctl daemon-reload
systemd-analyze verify "${SERVICE_FILE}" "${TIMER_FILE}"

validation_dir="$(mktemp -d /run/pitchai-auth-reset-guardian-validation.XXXXXX)"
cleanup_validation() {
  rm -rf -- "${validation_dir}"
}
trap cleanup_validation EXIT
"${RUNNER}" --audit-db "${validation_dir}/simulation.sqlite3" run \
  --simulate "${CURRENT_LINK}/fixtures/auth-reset-guardian-expiring.json" \
  --now 2026-08-11T19:30:00Z \
  --no-notify >/dev/null
"${RUNNER}" --audit-db "${AUDIT_DB}" run --dry-run --no-notify >/dev/null

rollback() {
  systemctl disable --now pitchai-auth-reset-guardian.timer >/dev/null 2>&1 || true
  if [[ -n "${previous_target}" && -d "${previous_target}" ]]; then
    rollback_link="${INSTALL_BASE}/.rollback-$$"
    ln -s "${previous_target}" "${rollback_link}"
    mv -Tf "${rollback_link}" "${CURRENT_LINK}"
  else
    rm -f -- "${CURRENT_LINK}"
  fi
}
if ! systemctl enable --now pitchai-auth-reset-guardian.timer; then
  rollback
  exit 1
fi
if ! systemctl start pitchai-auth-reset-guardian.service; then
  journalctl -u pitchai-auth-reset-guardian.service -n 100 --no-pager >&2 || true
  rollback
  exit 1
fi
systemctl is-active --quiet pitchai-auth-reset-guardian.timer
systemctl is-enabled --quiet pitchai-auth-reset-guardian.timer
"${RUNNER}" --audit-db "${AUDIT_DB}" status >/dev/null

cleanup_validation
trap - EXIT
printf 'Deployed reset guardian release %s; timer active; audit %s\n' "${release_id}" "${AUDIT_DB}"
