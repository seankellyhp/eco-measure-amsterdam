"""The run folder contract: run.json, session.json, status.json, stop; and the orphan sweep."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import paths, procs

LIVE_STATES = ("starting", "running")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: dict) -> None:
    """Write atomically: a reader never sees half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a reader holds the target open
            time.sleep(0.05)
    os.replace(tmp, path)


def status(rundir: Path) -> dict:
    return read_json(Path(rundir) / "status.json") or {}


def update_status(rundir: Path, **fields) -> dict:
    st = status(rundir)
    st.update(fields)
    write_json(Path(rundir) / "status.json", st)
    return st


def run_info(rundir: Path) -> dict:
    return read_json(Path(rundir) / "run.json") or {}


def session(rundir: Path) -> dict | None:
    return read_json(Path(rundir) / "session.json")


def monitor_alive(st: dict) -> bool:
    return procs.alive(st.get("pid"), st.get("create_time"))


def is_live(rundir: Path) -> bool:
    st = status(rundir)
    return st.get("state") in LIVE_STATES and monitor_alive(st)


def agent_alive(info: dict) -> bool:
    agent = info.get("agent") or {}
    return procs.alive(agent.get("pid"), agent.get("create_time"))


def agent_gone_reason(info: dict) -> str:
    agent = info.get("agent") or {}
    return f"agent {agent.get('name', '?')} (pid {agent.get('pid')}) exited"


def request_stop(rundir: Path, reason: str = "") -> None:
    (Path(rundir) / "stop").write_text(reason)


def wait_stopped(rundir: Path, timeout: float) -> bool:
    """Wait for the monitor to write state: stopped (or die)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = status(rundir)
        if st.get("state") in ("stopped", "failed"):
            return True
        if not monitor_alive(st):
            return False
        time.sleep(0.25)
    return False


def force_stop(rundir: Path, why: str) -> None:
    """Kill a monitor that would not stop, and record what the figures mean."""
    st = status(rundir)
    procs.stop_process(st.get("pid"), st.get("create_time"))
    as_of = st.get("last_flush_at") or "the last flush"
    update_status(
        rundir,
        state="stopped",
        ended_at=st.get("last_flush_at") or now_iso(),
        stopped_by=f"{why} (monitor killed - figures as of {as_of})",
    )
    try:
        (Path(rundir) / "stop").unlink()
    except OSError:
        pass


def sweep() -> None:
    """Close runs whose monitor died, and stop monitors whose agent is gone.

    Runs bound to a live agent are never touched.
    """
    root = paths.data_root()
    for label in paths.all_labels():
        rundir = root / label
        st = status(rundir)
        if st.get("state") not in LIVE_STATES:
            continue
        if not monitor_alive(st):
            update_status(
                rundir,
                state="stopped",
                stopped_by="monitor died",
                ended_at=st.get("last_flush_at") or now_iso(),
            )
            continue
        info = run_info(rundir)
        if not agent_alive(info):
            reason = agent_gone_reason(info)
            print(f"Stopping orphaned run '{label}': {reason}.", file=sys.stderr)
            request_stop(rundir, reason)
            if not wait_stopped(rundir, 15):
                force_stop(rundir, reason)
