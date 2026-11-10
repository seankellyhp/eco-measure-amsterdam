#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

MONITOR_PID="$1"
HARNESS_PID="$2"
HARNESS_START="$3"
RUNDIR="$4"
POLL="${CARBON_WATCHDOG_POLL:-5}"

trap 'exit 0' TERM INT

while true; do
  kill -0 "$MONITOR_PID" 2>/dev/null || exit 0
  if ! harness_alive "$HARNESS_PID" "$HARNESS_START"; then
    stop_monitor "$MONITOR_PID" "$RUNDIR" "watchdog: harness $HARNESS_PID exited"
    exit 0
  fi
  sleep "$POLL"
done
