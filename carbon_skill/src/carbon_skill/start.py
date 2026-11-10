"""carbon start: bind a run to this agent session and launch the monitor."""

from __future__ import annotations

import glob
import os
import sys
import time
from pathlib import Path

from . import __version__, db, locate, paths, procs, runs, tokens

MEASURED_CPU = {"RAPL", "PowerMetrics", "Power Gadget", "Windows EMI"}
MEASURED_GPU = {"pynvml", "amdsmi", "PowerMetrics"}


def measure_secs() -> float:
    raw = os.environ.get("CARBON_MEASURE_SECS", "").strip()
    try:
        value = float(raw) if raw else 10.0
    except ValueError:
        raise paths.UsageError(f"CARBON_MEASURE_SECS must be a number of seconds, not {raw!r}")
    return value if value > 0 else 10.0


def cpu_power_advice(method: str) -> str | None:
    """How to get a real CPU measurement here. Printed, never executed."""
    if method in MEASURED_CPU:
        return None
    if sys.platform == "darwin":
        return f"""NOTE: CPU power is an ESTIMATE ({method}), not a measurement.
  On macOS codecarbon estimates CPU power from CPU utilisation. Per codecarbon's
  docs there is no known way to read Apple Silicon energy without
  administrative rights, so there is nothing to enable. Report CPU figures as
  estimates."""
    if sys.platform == "win32":
        return f"""NOTE: CPU power is an ESTIMATE ({method}), not a measurement.
  On Windows codecarbon reads CPU energy only through the Energy Meter
  Interface (Windows 11 on bare metal, not a VM) or Intel Power Gadget.
  Neither is available here, so it estimates CPU power from CPU load.
  Report CPU figures as estimates."""
    if glob.glob("/sys/class/powercap/intel-rapl*"):
        return f"""NOTE: CPU power is an ESTIMATE ({method}), not a measurement.
  This machine has RAPL energy counters, but they are root-only (a kernel
  default since CVE-2020-8694). codecarbon's guide to enabling them:
    https://docs.codecarbon.io/latest/how-to/enable-rapl/
  Until reboot (makes the counters readable by every local user):
    sudo chmod a+r /sys/class/powercap/*/energy_uj
  Permanently, for your user only (codecarbon's recommended setup; these lines
  work in bash, zsh and fish):
    sudo groupadd codecarbon
    sudo usermod -a -G codecarbon $USER
    printf '%s\\n' 'SUBSYSTEM=="powercap", ACTION=="add", TEST=="energy_uj", RUN+="/bin/chgrp codecarbon /sys%p/energy_uj", RUN+="/bin/chmod 0440 /sys%p/energy_uj"' | sudo tee /etc/udev/rules.d/99-codecarbon-rapl.rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger --subsystem-match=powercap --action=add
    # then log out and back in, so the new group applies
  Then run carbon_start again; it should say "CPU: RAPL (measured)"."""
    return f"""NOTE: CPU power is an ESTIMATE ({method}), not a measurement.
  No RAPL interface at /sys/class/powercap (common in VMs, containers and on
  some CPUs), so codecarbon cannot read CPU energy here. Report CPU figures as
  estimates."""


def _tail(path: Path, n: int = 15) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return "(no monitor.log)"


def launch(label: str, quiet: bool = False) -> dict:
    """Insert a new run and start its monitor; return the run.

    Earlier runs with the same label are kept. Raises paths.Failure if the
    monitor does not reach `running`.
    """
    paths.check_label(label)
    runs.sweep()
    root = paths.data_root()
    interval = measure_secs()
    country, region, desc = locate.resolve(root / ".location")
    for other in db.live_with_label(label):
        if runs.is_live(other):
            raise paths.Failure(
                f"A monitor for '{label}' is already running (@{other['id']}, pid {other.get('monitor_pid')}).\n"
                f"Stop it with: carbon end {label}"
            )

    agent = procs.detect_agent()
    try:
        sess = tokens.resolve_session(str(agent["pid"]), os.getcwd())
    except Exception:
        sess = None

    run_id = db.insert_run({
        "label": label,
        "state": "starting",
        "created_at": runs.now_iso(),
        "agent_pid": agent["pid"],
        "agent_ctime": agent.get("create_time"),
        "agent_name": agent.get("name"),
        "agent_how": agent.get("how"),
        "cwd": os.getcwd(),
        "measure_secs": interval,
        "grid_country": country,
        "grid_region": region,
        "grid_source": desc,
        "carbon_version": __version__,
    }, sess)
    rundir = paths.run_dir(run_id)
    log = rundir / "monitor.log"
    try:
        rundir.mkdir(parents=True, exist_ok=True)
        proc = procs.spawn_detached(
            [sys.executable, "-m", "carbon_skill", "_monitor", str(run_id)], log, rundir
        )
        # Recorded at once, so a sweep from another command never takes the
        # run for one whose monitor died.
        runs.update_status(run_id, monitor_pid=proc.pid, monitor_ctime=procs.create_time(proc.pid))
    except BaseException as exc:
        runs.update_status(run_id, state="failed", error=f"could not start the monitor: {exc!r}")
        raise

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = runs.status(run_id).get("state")
        if state in ("running", "failed"):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    st = runs.status(run_id)
    if st.get("state") != "running":
        if proc.poll() is None and st.get("state") != "failed":
            procs.stop_process(proc.pid, None)
        runs.update_status(run_id, state="failed", error=st.get("error") or "monitor did not start")
        raise paths.Failure("Monitor failed to start. Last lines of monitor.log:\n" + _tail(log))
    return st


def command(label: str | None) -> int:
    label = paths.check_label(label or "default")
    st = launch(label)
    cpu, gpu = st.get("cpu_method") or "unknown", st.get("gpu_method") or "unknown"

    print(f"Tracking '{label}' as @{st['id']}  (pid {st.get('monitor_pid')}, sampling every {st['measure_secs']:g}s)")
    print(f"Data: {db.path()}")
    region = f" / {st['grid_region']}" if st.get("grid_region") else ""
    print(f"Grid: {st['grid_country']}{region} - {st['grid_source']}")
    if "LOOKUP FAILED - assuming" in st["grid_source"]:
        print("WARNING: the electricity grid was not detected, so CO2e may be for the wrong country. "
              "Set CARBON_COUNTRY (ISO-3, e.g. NLD, DEU, GBR, USA) and start again.", file=sys.stderr)
    if cpu in MEASURED_CPU:
        print(f"CPU: {cpu} (measured)")
    else:
        print(f"CPU: {cpu} - ESTIMATE, not measured")
    if gpu in MEASURED_GPU:
        print(f"GPU: {gpu} (measured) - idle draw is included, so a CPU-only run still accrues GPU energy")
    else:
        print("GPU: none tracked")
    sys.stdout.flush()
    advice = cpu_power_advice(cpu)
    if advice:
        print(advice, file=sys.stderr)
        sys.stderr.flush()
    sess = runs.session(st)
    if sess:
        print(f"Tokens: {sess['harness']} - {sess.get('id') or sess['transcript']} (via {sess['how']})")
    else:
        sys.stdout.flush()
        print("Tokens: session NOT identified - the report will omit token counts", file=sys.stderr)
    print(f"Auto-stop: when {st['agent_name']} (pid {st['agent_pid']}) exits, the monitor stops this run")
    print(f"Stop with: carbon end {label}")
    return 0
