#!/usr/bin/env bash
# Shared helpers for carbon_start / carbon_end / carbon_report / watchdog.
# Portable across Linux and macOS: bash 3.2 compatible (macOS ships 3.2), and
# every process lookup has a /proc branch (Linux) and a `ps` branch (macOS).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CARBON_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_ROOT="${CARBON_RUN_ROOT:-$CARBON_ROOT/runs}"
OS="$(uname -s)"

if [ -x "$CARBON_ROOT/.venv/bin/codecarbon-real" ]; then
  CODECARBON_BIN="$CARBON_ROOT/.venv/bin/codecarbon-real"
else
  CODECARBON_BIN=""
fi
if [ -x "$CARBON_ROOT/.venv/bin/python" ]; then
  PYBIN="$CARBON_ROOT/.venv/bin/python"
else
  PYBIN="$(command -v python3 || true)"
fi
# The grid (country/region) is resolved per run by locate.py in carbon_start.
MEASURE_SECS="${CARBON_MEASURE_SECS:-10}"

label_or_default() {
  local label="${1:-}"
  if [ -n "$label" ]; then
    printf '%s\n' "$label"
    return
  fi
  if [ -f "$RUN_ROOT/.last" ]; then
    cat "$RUN_ROOT/.last"
  else
    echo "default"
  fi
}

rundir_for() { printf '%s/%s\n' "$RUN_ROOT" "$1"; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# ISO-8601 with offset, e.g. 2026-11-10T14:03:07+01:00. BSD date (macOS) has
# no -Iseconds, so use python, which both platforms have in the skill's venv.
now_iso() {
  "$PYBIN" -c 'from datetime import datetime; print(datetime.now().astimezone().isoformat(timespec="seconds"))'
}

# Prefix that runs a command in a new session, detached from the caller's
# terminal and process group:   "${DETACH[@]}" cmd args... &
# Both forms exec the command in place, so `$!` is the command's own pid - which
# is what carbon_end signals. (This must be an array, not a function: `func &`
# forks a subshell, `$!` would be the subshell, and SIGTERM would never reach
# codecarbon, so it would not save its CSV.)
# Linux has setsid(1); macOS does not, so use python's os.setsid() there.
if command -v setsid >/dev/null 2>&1; then
  DETACH=(setsid)
else
  DETACH=("$PYBIN" -c 'import os, sys
try:
    os.setsid()
except OSError:
    pass
os.execvp(sys.argv[1], sys.argv[1:])')
fi

# --------------------------------------------------------------------------- #
# process lookups
# --------------------------------------------------------------------------- #

if [ "$OS" = "Linux" ]; then
  proc_field() {
    sed 's/(.*)/X/' "/proc/$1/stat" 2>/dev/null | awk -v n="$2" '{print $n}'
  }
  proc_ppid()  { proc_field "$1" 4; }
  # start time in clock ticks since boot: unique per pid incarnation
  proc_start() { proc_field "$1" 22; }
  proc_comm()  { cat "/proc/$1/comm" 2>/dev/null; }
else
  proc_ppid()  { ps -o ppid= -p "$1" 2>/dev/null | tr -d ' '; }
  # wall-clock start time (1 s resolution): a recycled pid would also need to
  # start in the same second to masquerade as the harness
  proc_start() { LC_ALL=C ps -o lstart= -p "$1" 2>/dev/null | sed 's/^ *//;s/ *$//'; }
  proc_comm()  {
    local c
    c="$(ps -o comm= -p "$1" 2>/dev/null)" || return 0
    c="${c##*/}"     # macOS prints the full path
    printf '%s\n' "${c#-}"   # login shells show as -zsh
  }
fi

# The session this run belongs to: the first ancestor that is not a shell or a
# launcher - the harness itself (e.g. `claude`).
detect_harness_pid() {
  if [ -n "${CARBON_PARENT_PID:-}" ]; then
    printf '%s\n' "$CARBON_PARENT_PID"
    return
  fi
  local p last comm
  p="$(proc_ppid "$$")"
  last="$p"
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    comm="$(proc_comm "$p")"
    comm="${comm#-}"
    case "$comm" in
      bash|sh|fish|zsh|dash|ksh|tcsh|csh|setsid|env|timeout|nohup|script|login|sudo) ;;
      *) printf '%s\n' "$p"; return ;;
    esac
    last="$p"
    p="$(proc_ppid "$p")"
  done
  printf '%s\n' "$last"
}

harness_alive() {
  local pid="$1" start="$2"
  kill -0 "$pid" 2>/dev/null || return 1
  [ -z "$start" ] || [ "$(proc_start "$pid")" = "$start" ] || return 1
  return 0
}

# --------------------------------------------------------------------------- #
# power measurement mode - as codecarbon itself decided it
# --------------------------------------------------------------------------- #
#
# The skill does not probe RAPL itself. codecarbon picks its CPU backend at
# start-up and logs it ("CPU Tracking Method: RAPL"); we read that line, so the
# skill can never disagree with the tool that does the measuring.

# Wait (up to $2 s) for codecarbon to log its tracking methods, then print
# "<cpu method>|<gpu method>".
read_tracking_methods() {
  local log="$1" wait="${2:-30}" i cpu gpu
  for i in $(seq 1 "$wait"); do
    grep -q 'CPU Tracking Method:' "$log" 2>/dev/null && break
    sleep 1
  done
  cpu="$(sed -n 's/.*CPU Tracking Method: *//p' "$log" 2>/dev/null | head -n1)"
  gpu="$(sed -n 's/.*GPU Tracking Method: *//p' "$log" 2>/dev/null | head -n1)"
  printf '%s|%s\n' "${cpu:-unknown}" "${gpu:-unknown}"
}

# Is this codecarbon CPU method a hardware energy reading (vs an estimate)?
cpu_method_measured() {
  case "$1" in
    RAPL|PowerMetrics|"Power Gadget"|"Windows EMI") return 0 ;;
    *) return 1 ;;
  esac
}

gpu_method_measured() {
  case "$1" in
    pynvml|amdsmi|PowerMetrics) return 0 ;;
    *) return 1 ;;
  esac
}

# How to get a real CPU measurement on this machine, following codecarbon's
# own documentation. Printed, never executed: every fix needs the user's sudo.
cpu_power_advice() {
  local method="$1"
  cpu_method_measured "$method" && return 0
  if [ "$OS" = "Darwin" ]; then
    cat >&2 <<MSG
NOTE: CPU power is an ESTIMATE ($method), not a measurement.
  On macOS codecarbon estimates CPU power from CPU utilisation. Per codecarbon's
  docs there is no known way to read Apple Silicon energy without
  administrative rights, so there is nothing to enable. Report CPU figures as
  estimates.
MSG
  elif ls -d /sys/class/powercap/intel-rapl* >/dev/null 2>&1; then
    cat >&2 <<MSG
NOTE: CPU power is an ESTIMATE ($method), not a measurement.
  This machine has RAPL energy counters, but they are root-only (a kernel
  default since CVE-2020-8694). codecarbon's guide to enabling them:
    https://docs.codecarbon.io/latest/how-to/enable-rapl/
  Until reboot (makes the counters readable by every local user):
    sudo chmod a+r /sys/class/powercap/*/energy_uj
  Permanently, for your user only (codecarbon's recommended setup; these lines
  work in bash, zsh and fish):
    sudo groupadd codecarbon
    sudo usermod -a -G codecarbon \$USER
    printf '%s\\n' 'SUBSYSTEM=="powercap", ACTION=="add", TEST=="energy_uj", RUN+="/bin/chgrp codecarbon /sys%p/energy_uj", RUN+="/bin/chmod 0440 /sys%p/energy_uj"' | sudo tee /etc/udev/rules.d/99-codecarbon-rapl.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=powercap --action=add
    # then log out and back in, so the new group applies
  Then run carbon_start again; it should say "CPU: RAPL (measured)".
MSG
  else
    cat >&2 <<MSG
NOTE: CPU power is an ESTIMATE ($method), not a measurement.
  No RAPL interface at /sys/class/powercap (common in VMs, containers and on
  some CPUs), so codecarbon cannot read CPU energy here. Report CPU figures as
  estimates.
MSG
  fi
}

# --------------------------------------------------------------------------- #
# stopping
# --------------------------------------------------------------------------- #

stop_monitor() {
  local pid="$1" rundir="$2" reason="$3"
  kill -TERM "$pid" 2>/dev/null || true
  local i
  for i in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
    sleep 1
    reason="$reason (SIGKILL - final row lost)"
  fi
  rm -f "$rundir/monitor.pid"
  now_iso > "$rundir/ended_at"
  printf '%s\n' "$reason" > "$rundir/stopped_by"
}

reap_orphaned_runs() {
  local dir label mpid hpid hstart
  [ -d "$RUN_ROOT" ] || return 0
  for dir in "$RUN_ROOT"/*/; do
    [ -f "$dir/monitor.pid" ] || continue
    mpid="$(cat "$dir/monitor.pid" 2>/dev/null || true)"
    pid_alive "$mpid" || { rm -f "$dir/monitor.pid"; continue; }
    hpid="$(cat "$dir/harness.pid" 2>/dev/null || true)"
    [ -n "$hpid" ] || continue
    hstart="$(cat "$dir/harness.start" 2>/dev/null || true)"
    if ! harness_alive "$hpid" "$hstart"; then
      label="$(basename "$dir")"
      echo "Reaping orphaned monitor for '$label' (pid $mpid): its harness (pid $hpid) is gone." >&2
      stop_monitor "$mpid" "${dir%/}" "orphan sweep: harness $hpid exited"
      kill -TERM "$(cat "$dir/watchdog.pid" 2>/dev/null || echo 0)" 2>/dev/null || true
    fi
  done
}
