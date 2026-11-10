#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

LABEL="${1:-default}"
RUNDIR="$(rundir_for "$LABEL")"
PIDFILE="$RUNDIR/monitor.pid"

reap_orphaned_runs

if [ -z "$CODECARBON_BIN" ] || [ ! -x "$CODECARBON_BIN" ] || [ ! -x "$CARBON_ROOT/.venv/bin/python" ]; then
  echo "The carbon skill is not installed: $CARBON_ROOT/.venv is missing or incomplete." >&2
  echo "Run the installer from the repository you got the skill from:" >&2
  echo "    bash carbon_skill/install.sh" >&2
  exit 1
fi

if [ -f "$PIDFILE" ] && pid_alive "$(cat "$PIDFILE")"; then
  echo "A monitor for '$LABEL' is already running (pid $(cat "$PIDFILE"))." >&2
  echo "Stop it with: carbon_end $LABEL" >&2
  exit 1
fi
rm -f "$PIDFILE"

mkdir -p "$RUNDIR"
printf '%s\n' "$LABEL" > "$RUN_ROOT/.last"

cat > "$RUNDIR/.codecarbon.config" <<CFG
[codecarbon]
project_name = $LABEL
measure_power_secs = $MEASURE_SECS
output_dir = $RUNDIR
output_file = emissions.csv
save_to_file = true
CFG

HARNESS_PID="$(detect_harness_pid)"
HARNESS_START="$(proc_start "$HARNESS_PID")"
HARNESS_COMM="$(proc_comm "$HARNESS_PID")"
printf '%s\n' "$HARNESS_PID" > "$RUNDIR/harness.pid"
printf '%s\n' "$HARNESS_START" > "$RUNDIR/harness.start"
printf '%s\n' "$HARNESS_COMM" > "$RUNDIR/harness.comm"
rm -f "$RUNDIR/stopped_by" "$RUNDIR/power_mode"

PWD_AT_START="$PWD"

# Which electricity grid: CARBON_COUNTRY if set, else detected from the public
# IP the way codecarbon's online mode does it (see locate.py), then fixed for
# the whole run. Recorded in the run dir as `grid`.
GRID_LINE="$("$PYBIN" "$SCRIPT_DIR/locate.py" "$RUN_ROOT/.location" 2>/dev/null || true)"
[ -n "$GRID_LINE" ] || GRID_LINE="$(printf 'NLD\t-\tLOCATION LOOKUP FAILED - assuming NLD; set CARBON_COUNTRY')"
COUNTRY="$(printf '%s\n' "$GRID_LINE" | cut -f1)"
REGION="$(printf '%s\n' "$GRID_LINE" | cut -f2)"
GRID_DESC="$(printf '%s\n' "$GRID_LINE" | cut -f3-)"
REGION_ARGS=()
[ "$REGION" != "-" ] && [ -n "$REGION" ] && REGION_ARGS=(--region "$REGION")
printf '%s%s - %s\n' "$COUNTRY" "${REGION_ARGS[1]:+ / ${REGION_ARGS[1]}}" "$GRID_DESC" > "$RUNDIR/grid"

cd "$RUNDIR"
"${DETACH[@]}" "$CODECARBON_BIN" monitor \
  --no-api --offline --country-iso-code "$COUNTRY" ${REGION_ARGS[@]+"${REGION_ARGS[@]}"} \
  --measure-power-secs "$MEASURE_SECS" --log-level info \
  > "$RUNDIR/monitor.log" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$PIDFILE"

sleep 3
if ! pid_alive "$PID"; then
  rm -f "$PIDFILE"
  echo "Monitor failed to start. Last lines of monitor.log:" >&2
  tail -n 15 "$RUNDIR/monitor.log" >&2
  exit 1
fi

now_iso > "$RUNDIR/started_at"
rm -f "$RUNDIR/ended_at"

# Bind token accounting to this session, exactly as the watchdog binds the
# monitor's lifetime to it. Resolved here and only here: this process is a child
# of the harness, so it still sees the harness environment.
rm -f "$RUNDIR/session.json"
if "$PYBIN" "$SCRIPT_DIR/tokens.py" --resolve "$HARNESS_PID" "$PWD_AT_START" \
     > "$RUNDIR/session.json" 2>/dev/null && [ -s "$RUNDIR/session.json" ]; then
  SESSION_DESC="$("$PYBIN" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["harness"], "-", d.get("id") or d["transcript"], "(via", d["how"] + ")")' "$RUNDIR/session.json")"
else
  rm -f "$RUNDIR/session.json"
  SESSION_DESC=""
fi

"${DETACH[@]}" bash "$SCRIPT_DIR/watchdog.sh" "$PID" "$HARNESS_PID" "$HARNESS_START" "$RUNDIR" \
  >> "$RUNDIR/watchdog.log" 2>&1 < /dev/null &
printf '%s\n' "$!" > "$RUNDIR/watchdog.pid"

# Which power sources codecarbon chose (it logs them once set-up is done).
METHODS="$(read_tracking_methods "$RUNDIR/monitor.log" 30)"
CPU_METHOD="${METHODS%%|*}"
GPU_METHOD="${METHODS#*|}"
if cpu_method_measured "$CPU_METHOD"; then CPU_KIND=measured; else CPU_KIND=ESTIMATE; fi
if gpu_method_measured "$GPU_METHOD"; then GPU_KIND=measured; else GPU_KIND=none; fi
printf 'cpu: %s (%s); gpu: %s (%s)\n' "$CPU_METHOD" "$CPU_KIND" "$GPU_METHOD" "$GPU_KIND" > "$RUNDIR/power_mode"

echo "Tracking '$LABEL'  (pid $PID, sampling every ${MEASURE_SECS}s)"
echo "Run dir: $RUNDIR"
echo "Grid: $(cat "$RUNDIR/grid")"
case "$GRID_DESC" in
  *"LOOKUP FAILED - assuming"*) echo "WARNING: the electricity grid was not detected, so CO2e may be for the wrong country. Set CARBON_COUNTRY (ISO-3, e.g. NLD, DEU, GBR, USA) and start again." >&2 ;;
esac
if [ "$CPU_KIND" = measured ]; then
  echo "CPU: $CPU_METHOD (measured)"
else
  echo "CPU: $CPU_METHOD - ESTIMATE, not measured"
fi
if [ "$GPU_KIND" = measured ]; then
  echo "GPU: $GPU_METHOD (measured) - idle draw is included, so a CPU-only run still accrues GPU energy"
else
  echo "GPU: none tracked"
fi
cpu_power_advice "$CPU_METHOD"
if [ -n "$SESSION_DESC" ]; then
  echo "Tokens: $SESSION_DESC"
else
  echo "Tokens: session NOT identified - the report will omit token counts" >&2
fi
echo "Auto-stop: when $HARNESS_COMM (pid $HARNESS_PID) exits, a watchdog stops this run"
echo "Stop with: carbon_end $LABEL"
