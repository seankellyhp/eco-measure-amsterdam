#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

reap_orphaned_runs

LABEL="$(label_or_default "${1:-}")"
RUNDIR="$(rundir_for "$LABEL")"
CSV="$RUNDIR/emissions.csv"

SCRIPTS="$(dirname "${BASH_SOURCE[0]}")"
MODE="$(cat "$RUNDIR/power_mode" 2>/dev/null || echo unknown)"

RUNNING=no
if [ -f "$RUNDIR/monitor.pid" ] && pid_alive "$(cat "$RUNDIR/monitor.pid")"; then RUNNING=yes; fi

if [ ! -f "$CSV" ] || [ "$RUNNING" = yes ]; then
  if [ -f "$RUNDIR/monitor.log" ] && [ -f "$RUNDIR/started_at" ]; then
    exec "$PYBIN" "$SCRIPTS/report_live.py" "$RUNDIR/monitor.log" "$(cat "$RUNDIR/started_at")" "$LABEL" "$MODE" "$RUNDIR"
  fi
  echo "No emissions.csv in $RUNDIR." >&2
  if [ -f "$RUNDIR/monitor.log" ]; then
    echo "The monitor has not completed a measurement yet. monitor.log tail:" >&2
    tail -n 10 "$RUNDIR/monitor.log" >&2
  else
    echo "No such run. Available runs:" >&2
    ls -1 "$RUN_ROOT" 2>/dev/null | grep -v '^\.' >&2 || echo "  (none)" >&2
  fi
  exit 1
fi

[ -f "$RUNDIR/stopped_by" ] && echo "(stopped by: $(cat "$RUNDIR/stopped_by"))"
"$PYBIN" "$SCRIPTS/report.py" "$CSV" "$LABEL" "$RUNNING" "$MODE" "$RUNDIR"
