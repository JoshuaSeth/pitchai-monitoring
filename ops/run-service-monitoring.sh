#!/bin/sh

# Restart the container if a wedged monitor stops publishing completed cycles.
# Docker's unless-stopped policy turns exit 75 into a clean, bounded recovery.

state_path=${MONITOR_WATCHDOG_STATE_PATH:-${STATE_PATH:-/data/state.json}}
stale_after=${MONITOR_STALE_AFTER_SECONDS:-600}
poll_seconds=${MONITOR_WATCHDOG_POLL_SECONDS:-15}
stop_grace=${MONITOR_STOP_GRACE_SECONDS:-15}

require_positive_integer() {
  value=$1
  name=$2
  case "$value" in
    ""|*[!0-9]*|0)
      echo "$name must be a positive integer" >&2
      exit 64
      ;;
  esac
}

require_positive_integer "$stale_after" MONITOR_STALE_AFTER_SECONDS
require_positive_integer "$poll_seconds" MONITOR_WATCHDOG_POLL_SECONDS
require_positive_integer "$stop_grace" MONITOR_STOP_GRACE_SECONDS

if [ "$#" -eq 0 ]; then
  set -- python -m domain_checks.main
fi

child_pid=
watchdog_pid=
stale_marker=$(mktemp /tmp/service-monitoring-watchdog.XXXXXX) || exit 70
rm -f "$stale_marker"

stop_process() {
  target_pid=$1
  if ! kill -0 "$target_pid" 2>/dev/null; then
    return
  fi
  kill -TERM "$target_pid" 2>/dev/null || true
  waited=0
  while kill -0 "$target_pid" 2>/dev/null && [ "$waited" -lt "$stop_grace" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$target_pid" 2>/dev/null; then
    kill -KILL "$target_pid" 2>/dev/null || true
  fi
}

stop_watchdog() {
  if [ -n "$watchdog_pid" ] && kill -0 "$watchdog_pid" 2>/dev/null; then
    kill -TERM "$watchdog_pid" 2>/dev/null || true
  fi
  if [ -n "$watchdog_pid" ]; then
    wait "$watchdog_pid" 2>/dev/null || true
  fi
}

handle_signal() {
  exit_status=$1
  trap - TERM INT
  stop_watchdog
  if [ -n "$child_pid" ]; then
    stop_process "$child_pid"
    wait "$child_pid" 2>/dev/null || true
  fi
  rm -f "$stale_marker"
  exit "$exit_status"
}

watch_state() {
  monitored_pid=$1
  last_progress=$(date +%s)
  while kill -0 "$monitored_pid" 2>/dev/null; do
    sleep "$poll_seconds"
    now=$(date +%s)
    state_mtime=$(stat -c %Y "$state_path" 2>/dev/null || printf '0')
    case "$state_mtime" in
      ""|*[!0-9]*) state_mtime=0 ;;
    esac
    if [ "$state_mtime" -gt "$last_progress" ]; then
      last_progress=$state_mtime
    fi
    if [ $((now - last_progress)) -ge "$stale_after" ]; then
      : >"$stale_marker"
      echo "service-monitoring watchdog: completed-cycle state is stale; terminating monitor" >&2
      stop_process "$monitored_pid"
      return
    fi
  done
}

trap 'handle_signal 143' TERM
trap 'handle_signal 130' INT

"$@" &
child_pid=$!
watch_state "$child_pid" &
watchdog_pid=$!

wait "$child_pid"
child_status=$?
stop_watchdog

if [ -f "$stale_marker" ]; then
  rm -f "$stale_marker"
  exit 75
fi

rm -f "$stale_marker"
exit "$child_status"
