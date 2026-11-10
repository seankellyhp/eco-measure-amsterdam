#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

LABEL="$(label_or_default "${1:-}")"
RUNDIR="$(rundir_for "$LABEL")"
PIDFILE="$RUNDIR/monitor.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "No monitor.pid for '$LABEL' - nothing running." >&2
  echo "(If the run already finished, use: carbon_report $LABEL)" >&2
  exit 1
fi

WPID="$(cat "$RUNDIR/watchdog.pid" 2>/dev/null || true)"
[ -n "$WPID" ] && kill -TERM "$WPID" 2>/dev/null || true
rm -f "$RUNDIR/watchdog.pid"

PID="$(cat "$PIDFILE")"
if ! pid_alive "$PID"; then
  echo "Monitor for '$LABEL' (pid $PID) is already gone; reporting what was saved." >&2
  rm -f "$PIDFILE"
  [ -f "$RUNDIR/ended_at" ] || now_iso > "$RUNDIR/ended_at"
else
  stop_monitor "$PID" "$RUNDIR" "carbon_end"
  echo "Stopped '$LABEL'."
  echo
fi

exec "$(dirname "${BASH_SOURCE[0]}")/carbon_report.sh" "$LABEL"
