#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SCRIPT="$SCRIPT_DIR/pitchai-montrachet-demo-disk-reserve"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT

OUTPUT=""
COMMANDS=""
RESERVE_EXISTS=0

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_contains() {
  local haystack=$1
  local needle=$2
  local message=$3
  grep -Fq -- "$needle" <<<"$haystack" || fail "$message"
}

assert_not_contains() {
  local haystack=$1
  local needle=$2
  local message=$3
  if grep -Fq -- "$needle" <<<"$haystack"; then
    fail "$message"
  fi
}

assert_equals() {
  local expected=$1
  local actual=$2
  local message=$3
  [ "$actual" = "$expected" ] || fail "$message (expected=$expected actual=$actual)"
}

write_executable() {
  local path=$1
  local contents=$2
  printf '%s' "$contents" >"$path"
  chmod 0755 "$path"
}

run_guard() {
  local case_name=$1
  local reserve_size=$2
  shift 2

  local root="$TEST_ROOT/$case_name"
  local state="$root/state"
  local logs="$root/logs"
  local fake_bin="$root/bin"
  local values_file="$root/df-values"
  local index_file="$root/df-index"
  local command_log="$root/commands"
  local output_file="$root/output"
  mkdir -p -- "$state" "$logs" "$fake_bin"
  printf '%s\n' "$@" >"$values_file"
  printf '0\n' >"$index_file"

  if [ "$reserve_size" != "none" ]; then
    truncate -s "$reserve_size" "$state/reserve.bin"
  fi

  local df_stub
  df_stub=$(cat <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
index=$(<"$DF_INDEX_FILE")
line=$((index + 1))
value=$(sed -n "${line}p" "$DF_VALUES_FILE")
if [ -z "$value" ]; then
  value=$(tail -1 "$DF_VALUES_FILE")
fi
printf "%s\n" "$((index + 1))" >"$DF_INDEX_FILE"
printf "Avail\n%s\n" "$value"
EOF
)
  local command_stub
  command_stub=$(cat <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf "%s %s\n" "${0##*/}" "$*" >>"$COMMAND_LOG"
if [ "${0##*/}" = logrotate ]; then
  config=${!#}
  printf '%s\n' 'logrotate-config-begin' >>"$COMMAND_LOG"
  sed 's/^/logrotate-config: /' "$config" >>"$COMMAND_LOG"
  printf '%s\n' 'logrotate-config-end' >>"$COMMAND_LOG"
fi
EOF
)
  write_executable "$fake_bin/df" "$df_stub"
  write_executable "$fake_bin/docker" "$command_stub"
  write_executable "$fake_bin/journalctl" "$command_stub"
  write_executable "$fake_bin/logrotate" "$command_stub"

  PATH="$fake_bin:$PATH" \
    STATE_DIR="$state" \
    LOG_DIR="$logs" \
    FS_PATH="$root" \
    RSYSLOG_LOGROTATE_CONF="$root/rsyslog" \
    DF_VALUES_FILE="$values_file" \
    DF_INDEX_FILE="$index_file" \
    COMMAND_LOG="$command_log" \
    RESERVE_TARGET_BYTES=2000 \
    FREE_CRITICAL_BYTES=500 \
    FREE_REARM_BYTES=4000 \
    CRISIS_FLOOR_BYTES=250 \
    FREE_EMERGENCY_BYTES=100 \
    "$SCRIPT" >"$output_file"

  OUTPUT=$(<"$output_file")
  if [ -f "$command_log" ]; then
    COMMANDS=$(<"$command_log")
  else
    COMMANDS=""
  fi
  if [ -f "$state/reserve.bin" ]; then
    RESERVE_EXISTS=1
  else
    RESERVE_EXISTS=0
  fi
}

run_guard release-below-rearm 2000 400 2400 6000
assert_equals 0 "$RESERVE_EXISTS" "reserve should be released"
assert_contains "$OUTPUT" "post-release available=2400B" "release headroom was not observed"
assert_contains "$OUTPUT" "post-release-reclaim available=6000B" "post-release reclaim did not run"
assert_contains "$COMMANDS" "docker image prune -af" "unused images were not reclaimed"
assert_contains "$COMMANDS" "docker builder prune -af" "build cache was not reclaimed"
assert_not_contains "$COMMANDS" "--filter" "crisis reclaim retained the age filter"

run_guard unarmed-crisis none 100 3000
assert_equals 0 "$RESERVE_EXISTS" "unarmed guard should remain unarmed"
assert_contains "$OUTPUT" "post-reclaim available=3000B" "unarmed crisis reclaim did not run"
assert_contains "$COMMANDS" "docker image prune -af" "unarmed crisis kept unused images"
assert_contains "$COMMANDS" "docker builder prune -af" "unarmed crisis kept build cache"

run_guard release-above-rearm 2000 400 4500
assert_equals 0 "$RESERVE_EXISTS" "reserve should be released above the rearm threshold"
assert_contains "$OUTPUT" "post-release available=4500B" "release headroom was not observed"
assert_not_contains "$OUTPUT" "post-release-reclaim" "healthy release reclaimed cache"
assert_equals "" "$COMMANDS" "healthy release touched host caches"

run_guard emergency-rotation none 50 75 200
assert_equals 0 "$RESERVE_EXISTS" "emergency guard should remain unarmed"
assert_contains "$OUTPUT" "post-emergency available=200B" "emergency rotation did not refresh headroom"
assert_contains "$COMMANDS" "logrotate -f " "emergency rotation did not call logrotate"
assert_contains "$COMMANDS" "logrotate-config: su root syslog" "emergency rotation omitted the secure identity"
assert_contains "$COMMANDS" "logrotate-config: include $TEST_ROOT/emergency-rotation/rsyslog" "emergency rotation omitted the distro policy"

printf 'PASS: 4 disk-reserve guard scenarios\n'
