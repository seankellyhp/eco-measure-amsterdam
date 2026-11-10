"""Run lifecycle on top of the database: state, the stop sentinel, the orphan
sweep, and which run a command means (label, @id, or this session's)."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from . import db, paths, procs

LIVE_STATES = db.LIVE
now_iso = db.now_iso


def status(run_id: int) -> dict:
    """The run row as a dict ({} if there is no such run)."""
    return db.get_run(run_id) or {}


def update_status(run_id: int, **fields) -> None:
    db.update_run(run_id, **fields)


def session(run: dict) -> dict | None:
    return run.get("session")


def run_dir(run: dict | int) -> Path:
    return paths.run_dir(run["id"] if isinstance(run, dict) else run)


def monitor_alive(run: dict) -> bool:
    return procs.alive(run.get("monitor_pid"), run.get("monitor_ctime"))


def is_live(run: dict | int) -> bool:
    if not isinstance(run, dict):
        run = status(run)
    return run.get("state") in LIVE_STATES and monitor_alive(run)


def agent_alive(run: dict) -> bool:
    return procs.alive(run.get("agent_pid"), run.get("agent_ctime"))


def agent_gone_reason(run: dict) -> str:
    return f"agent {run.get('agent_name') or '?'} (pid {run.get('agent_pid')}) exited"


def request_stop(run: dict, reason: str = "") -> None:
    folder = run_dir(run)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "stop").write_text(reason)


def wait_stopped(run: dict, timeout: float) -> bool:
    """Wait for the monitor to set state stopped (or failed), or die."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = status(run["id"])
        if st.get("state") in ("stopped", "failed"):
            return True
        if not monitor_alive(st):
            return False
        time.sleep(0.25)
    return False


def force_stop(run: dict, why: str) -> None:
    """Kill a monitor that would not stop, and record what the figures mean."""
    st = status(run["id"])
    procs.stop_process(st.get("monitor_pid"), st.get("monitor_ctime"))
    as_of = st.get("last_flush_at") or "the last flush"
    update_status(
        run["id"],
        state="stopped",
        ended_at=st.get("last_flush_at") or now_iso(),
        stopped_by=f"{why} (monitor killed - figures as of {as_of})",
    )
    try:
        (run_dir(run) / "stop").unlink()
    except OSError:
        pass


def _age(iso: str | None) -> float:
    try:
        return (datetime.now().astimezone() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def sweep() -> None:
    """Close runs whose monitor died, stop monitors whose agent is gone, and
    save the usage of any stopped run that does not have it yet.

    Runs bound to a live agent are never touched.
    """
    for run in db.live_runs():
        if not monitor_alive(run):
            if run.get("monitor_pid") is None:
                # `carbon start` is between the insert and the spawn - or died there.
                if _age(run.get("created_at")) > 60:
                    update_status(run["id"], state="failed", error="monitor was never started")
                continue
            update_status(
                run["id"],
                state="stopped",
                stopped_by="monitor died",
                ended_at=run.get("last_flush_at") or now_iso(),
            )
            continue
        if run.get("agent_pid") and not agent_alive(run):
            reason = agent_gone_reason(run)
            print(f"Stopping orphaned run '{run['label']}' (@{run['id']}): {reason}.", file=sys.stderr)
            request_stop(run, reason)
            if not wait_stopped(run, 15):
                force_stop(run, reason)
    pending = db.runs_needing_usage()
    if pending:
        from . import usage

        for run_id in pending:
            usage.save(run_id)


# --------------------------------------------------------------------------- #
# which run a command means
# --------------------------------------------------------------------------- #


def here() -> tuple[dict, dict | None, bool]:
    """(agent process, its session or None, whether we are inside an agent session).

    Inside means: the session was identified exactly, the agent was named by
    CARBON_PARENT_PID / CLAUDE_PID, or a known agent is an ancestor process.
    A session found only by guessing from the cwd does not count: a plain
    terminal in a project folder would match it.
    """
    from . import tokens

    agent = procs.detect_agent()
    try:
        sess = tokens.resolve_session(str(agent["pid"]), os.getcwd())
    except Exception:
        sess = None
    inside = (
        exact(sess) is not None
        or agent["how"] in ("CARBON_PARENT_PID", "CLAUDE_PID")
        or procs.under_known_agent()
    )
    return agent, sess, inside


def exact(sess: dict | None) -> dict | None:
    """The session, unless it was only guessed from the cwd. A guess can name
    another session's transcript (two sessions in one folder, or a plain
    terminal in a project folder), so it never selects a run."""
    if sess and "INFERRED" not in (sess.get("how") or ""):
        return sess
    return None


def current_run() -> tuple[dict | None, str]:
    """This session's run (5.3.1 of sqlite_plan.md), and which rule found it.

    Returns (None, reason) inside an agent session that started no run.
    """
    agent, sess, inside = here()
    sid = db.find_session(exact(sess))
    if sid is not None:
        run = db.newest_in_session(sid)
        if run:
            return run, "session"
    run = db.newest_for_agent(agent["pid"], agent.get("create_time"))
    if run:
        return run, "agent"
    if inside:
        return None, "No run was started in this session. See: carbon list"
    run = db.newest_run()
    if run is None:
        return None, f"No runs yet in {paths.data_root()}. Start one with: carbon start"
    print(f"No agent session detected; using the most recent run '{run['label']}' (@{run['id']}).",
          file=sys.stderr)
    return run, "newest"


def find(ref: str | None) -> dict:
    """The run a command argument names: a label (its newest run), '@<id>', or
    nothing (this session's run). Raises paths.Failure if there is none."""
    if not ref:
        run, why = current_run()
        if run is None:
            raise paths.Failure(why)
        return run
    label, run_id = paths.parse_ref(ref)
    run = db.get_run(run_id) if run_id is not None else db.newest_with_label(label)
    if run is None:
        raise paths.Failure(f"No run named '{ref}'. See: carbon list")
    return run


def name(run: dict) -> str:
    return f"'{run['label']}' (@{run['id']})"
