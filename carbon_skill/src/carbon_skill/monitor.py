"""The detached monitor: one process per run, owning one codecarbon tracker.

Started by `carbon start` as `python -m carbon_skill _monitor <run id>`. It
saves a cumulative `sample` row to the database every interval, so a hard kill
loses at most one interval, and it stops on the `stop` file in the run folder,
on a signal, or when the agent it is bound to exits.
"""

from __future__ import annotations

import logging
import re
import signal
import sqlite3
import sys
import time
from pathlib import Path

import psutil

from . import db, paths, runs

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


class SqliteOutput:
    """A CodeCarbon output handler that writes one `sample` row per flush.

    CodeCarbon calls `out(total, delta)` from flush() and stop(), on the
    monitor's main thread. `total` is cumulative since start(), so a row that
    fails to save is made up for by the next one: errors are printed to
    monitor.log and never raised into the tracker.
    """

    def __init__(self, conn, run_id: int) -> None:
        self.conn = conn
        self.run_id = run_id
        self.static_saved = False
        self.rows = 0

    def out(self, total, delta) -> None:
        try:
            values = dict(total.values)
            static = None if self.static_saved else db.static_from_codecarbon(values)
            db.add_sample(self.conn, self.run_id, db.sample_from_codecarbon(values), static)
            self.static_saved = True
            self.rows += 1
        except (sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
            print(f"carbon monitor: sample not saved: {exc!r}", file=sys.stderr)
            sys.stderr.flush()

    def live_out(self, total, delta) -> None:
        pass

    def task_out(self, data, experiment_name) -> None:
        pass

    def exit(self) -> None:
        pass


def _base_output():
    """SqliteOutput as a BaseOutput subclass, built lazily so importing this
    module does not import codecarbon."""
    from codecarbon.output_methods.base_output import BaseOutput

    return type("SqliteOutput", (SqliteOutput, BaseOutput), {})


def run(run_id_arg: str) -> int:
    run_id = int(run_id_arg)
    rundir_p = paths.run_dir(run_id)
    log = rundir_p / "monitor.log"
    conn = db.connect()
    info = db.get_run(run_id)
    if info is None:
        print(f"carbon monitor: no run @{run_id} in {db.path()}", file=sys.stderr)
        return 1
    me = psutil.Process()
    db.update_run(run_id, conn=conn, state="starting", monitor_pid=me.pid, monitor_ctime=me.create_time())

    capture = _MethodCapture()
    logging.getLogger("codecarbon").addHandler(capture)

    measure_secs = float(info.get("measure_secs") or 10)
    handler = _base_output()(conn, run_id)
    try:
        from codecarbon import OfflineEmissionsTracker

        tracker = OfflineEmissionsTracker(
            project_name=info["label"],
            country_iso_code=info.get("grid_country") or "NLD",
            region=info.get("grid_region") or None,
            measure_power_secs=measure_secs,
            output_dir=str(rundir_p),
            output_methods=[],
            output_handlers=[handler],
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
        db.update_run(run_id, conn=conn, state="failed", error=_log_tail(log) or "tracker did not start")
        return 1

    methods = capture.methods or methods_from_log(log)
    db.update_run(
        run_id,
        conn=conn,
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
        if info.get("agent_pid") and not runs.agent_alive(info):
            stop_reason.append(runs.agent_gone_reason(info))
            break
        if time.monotonic() >= next_flush:
            tracker.flush()
            next_flush += measure_secs
        time.sleep(1)

    tracker.stop()
    fields = {"state": "stopped", "ended_at": runs.now_iso(), "stopped_by": stop_reason[0]}
    if handler.rows == 0 and db.last_sample(run_id) is None:
        fields["error"] = "no sample was saved"
    db.update_run(run_id, conn=conn, **fields)
    conn.close()
    try:
        stop_file.unlink()
    except OSError:
        pass
    return 0
