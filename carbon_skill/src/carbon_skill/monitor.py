"""The detached monitor: one process per run, owning one codecarbon tracker.

Started by `carbon start` as `python -m carbon_skill _monitor <rundir>`. It
flushes a cumulative row to emissions.csv every interval, so a hard kill loses
at most one interval, and it stops on the `stop` file, on a signal, or when the
agent it is bound to exits.
"""

from __future__ import annotations

import logging
import re
import signal
import sys
import time
from pathlib import Path

import psutil

from . import procs, runs

METHOD_RE = re.compile(r"(CPU|GPU) Tracking Method:\s*(.+)")


class _MethodCapture(logging.Handler):
    """Pick up codecarbon's one-time 'CPU/GPU Tracking Method:' log lines."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.methods: dict[str, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        for kind, value in METHOD_RE.findall(msg):
            self.methods.setdefault(kind, value.strip())


def methods_from_log(log: Path) -> dict[str, str]:
    try:
        text = log.read_text(errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for kind, value in METHOD_RE.findall(text):
        out.setdefault(kind, value.strip())
    return out


def _log_tail(log: Path, n: int = 15) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def run(rundir: str) -> int:
    rundir_p = Path(rundir).resolve()
    log = rundir_p / "monitor.log"
    info = runs.run_info(rundir_p)
    me = psutil.Process()
    runs.write_json(
        rundir_p / "status.json",
        {"state": "starting", "pid": me.pid, "create_time": me.create_time()},
    )

    capture = _MethodCapture()
    logging.getLogger("codecarbon").addHandler(capture)

    grid = info.get("grid") or {}
    measure_secs = float(info.get("measure_secs") or 10)
    try:
        from codecarbon import OfflineEmissionsTracker

        tracker = OfflineEmissionsTracker(
            project_name=info.get("label", "carbon"),
            country_iso_code=grid.get("country") or "NLD",
            region=grid.get("region") or None,
            measure_power_secs=measure_secs,
            output_dir=str(rundir_p),
            output_file="emissions.csv",
            save_to_file=True,
            save_to_api=False,
            tracking_mode="machine",
            log_level="info",
            allow_multiple_runs=True,
        )
        tracker.start()
        started = getattr(tracker, "_start_time", None) is not None
    except Exception as exc:  # codecarbon suppresses most errors itself
        print(f"carbon monitor: {exc!r}", file=sys.stderr)
        started = False
    sys.stderr.flush()

    if not started:
        runs.update_status(rundir_p, state="failed", error=_log_tail(log) or "tracker did not start")
        return 1

    methods = capture.methods or methods_from_log(log)
    runs.update_status(
        rundir_p,
        state="running",
        started_at=runs.now_iso(),
        cpu_method=methods.get("CPU", "unknown"),
        gpu_method=methods.get("GPU", "unknown"),
    )

    stop_reason: list[str] = []

    def on_signal(signum, frame):
        stop_reason.append("signal")

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, on_signal)
            except (ValueError, OSError):
                pass

    agent = info.get("agent") or {}
    stop_file = rundir_p / "stop"
    next_flush = time.monotonic() + measure_secs
    while not stop_reason:
        if stop_file.exists():
            try:
                text = stop_file.read_text().strip()
            except OSError:
                text = ""
            stop_reason.append(text or "carbon end")
            break
        if agent.get("pid") and not procs.alive(agent.get("pid"), agent.get("create_time")):
            stop_reason.append(runs.agent_gone_reason(info))
            break
        if time.monotonic() >= next_flush:
            tracker.flush()
            runs.update_status(rundir_p, last_flush_at=runs.now_iso())
            next_flush += measure_secs
        time.sleep(1)

    tracker.stop()
    csv = rundir_p / "emissions.csv"
    fields = {"state": "stopped", "ended_at": runs.now_iso(), "stopped_by": stop_reason[0]}
    if not csv.is_file() or csv.stat().st_size == 0:
        fields["error"] = "emissions.csv missing or empty after stop"
    runs.update_status(rundir_p, **fields)
    try:
        stop_file.unlink()
    except OSError:
        pass
    return 0
