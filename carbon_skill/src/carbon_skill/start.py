"""carbon start: bind a run to this agent session and launch the monitor."""

from __future__ import annotations

import glob
import os
import sys
import time
from pathlib import Path

from . import __version__, locate, paths, procs, runs, tokens

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


def launch(label: str, quiet: bool = False, set_last: bool = True) -> Path:
    """Create the run folder and start its monitor; return the run dir.

    Raises paths.Failure if the monitor does not reach `running`.
    """
    paths.check_label(label)
    runs.sweep()
    root = paths.data_root()
    rundir = root / label
    if rundir.is_dir():
        if runs.is_live(rundir):
            raise paths.Failure(
                f"A monitor for '{label}' is already running (pid {runs.status(rundir).get('pid')}).\n"
                f"Stop it with: carbon end {label}"
            )
        if any(rundir.iterdir()):
            if not quiet:
                print(f"Replacing the previous '{label}' run.")
            paths.empty_dir(rundir)
    rundir.mkdir(parents=True, exist_ok=True)

    agent = procs.detect_agent()
    country, region, desc = locate.resolve(root / ".location")
    try:
        sess = tokens.resolve_session(str(agent["pid"]), os.getcwd())
    except Exception:
        sess = None

    runs.write_json(rundir / "run.json", {
        "label": label,
        "measure_secs": measure_secs(),
        "grid": {"country": country, "region": region, "description": desc},
        "agent": agent,
        "cwd": os.getcwd(),
        "version": __version__,
    })
    if sess:
        runs.write_json(rundir / "session.json", sess)
    if set_last:
        paths.set_last(label)

    log = rundir / "monitor.log"
    proc = procs.spawn_detached(
        [sys.executable, "-m", "carbon_skill", "_monitor", str(rundir)], log, rundir
    )

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = runs.status(rundir).get("state")
        if state in ("running", "failed"):
            break
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    st = runs.status(rundir)
    if st.get("state") != "running":
        if proc.poll() is None and st.get("state") != "failed":
            procs.stop_process(proc.pid, None)
        runs.update_status(rundir, state="failed", error=st.get("error") or "monitor did not start")
        raise paths.Failure("Monitor failed to start. Last lines of monitor.log:\n" + _tail(log))
    return rundir


def command(label: str | None) -> int:
    label = paths.check_label(label or "default")
    rundir = launch(label)
    info = runs.run_info(rundir)
    st = runs.status(rundir)
    grid = info["grid"]
    agent = info["agent"]
    cpu, gpu = st.get("cpu_method", "unknown"), st.get("gpu_method", "unknown")

    print(f"Tracking '{label}'  (pid {st.get('pid')}, sampling every {info['measure_secs']:g}s)")
    print(f"Run dir: {rundir}")
    region = f" / {grid['region']}" if grid.get("region") else ""
    print(f"Grid: {grid['country']}{region} - {grid['description']}")
    if "LOOKUP FAILED - assuming" in grid["description"]:
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
    sess = runs.session(rundir)
    if sess:
        print(f"Tokens: {sess['harness']} - {sess.get('id') or sess['transcript']} (via {sess['how']})")
    else:
        sys.stdout.flush()
        print("Tokens: session NOT identified - the report will omit token counts", file=sys.stderr)
    print(f"Auto-stop: when {agent['name']} (pid {agent['pid']}) exits, the monitor stops this run")
    print(f"Stop with: carbon end {label}")
    return 0
