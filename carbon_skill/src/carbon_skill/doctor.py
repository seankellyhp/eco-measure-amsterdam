"""carbon doctor: one line per check, `ok` or `PROBLEM: <what to do>`."""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time

from . import __version__, agents, db, paths, procs, runs, tokens

LABEL = "doctor-check"


def command(measure: bool = True) -> int:
    problems = 0

    def ok(what: str) -> None:
        print(f"ok       {what}")

    def bad(what: str) -> None:
        nonlocal problems
        problems += 1
        print(f"PROBLEM  {what}")

    ok(f"carbon-skill {__version__} at {os.path.dirname(os.path.abspath(__file__))}")
    v = sys.version_info
    (ok if v >= (3, 12) else bad)(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")

    for mod in ("codecarbon", "ecologits"):
        try:
            from importlib.metadata import version

            __import__(mod)
            ok(f"{mod} {version(mod)}")
        except Exception as exc:
            bad(f"{mod} does not import ({exc}): uv tool install --reinstall ./carbon_skill")

    try:
        root = paths.data_root()
        with tempfile.NamedTemporaryFile(dir=root):
            pass
        ok(f"data folder writable: {root}")
    except OSError as exc:
        bad(f"data folder not writable ({exc}): set CARBON_RUN_ROOT to a writable folder")

    sv = sqlite3.sqlite_version
    try:
        version, check = db.health()
        if check != "ok":
            bad(f"database {db.path()} fails its integrity check ({check}): "
                "back it up with `carbon export --format sql -o carbon.sql`, then move carbon.db aside")
        else:
            ok(f"database {db.path()} (schema {version}, SQLite {sv})")
    except paths.Failure as exc:
        bad(str(exc))
    except sqlite3.Error as exc:
        bad(f"database {db.path()} does not open ({exc}); SQLite {sv}")

    on_path = shutil.which("carbon")
    cmd = agents.carbon_cmd()
    if on_path:
        ok(f"carbon on PATH: {on_path}")
    elif cmd.startswith("uv run"):
        ok(f"carbon not on PATH; agents will call: {cmd}")
    else:
        bad("carbon is not on PATH: run `uv tool update-shell`, then open a new terminal")

    found = agents.detected()
    for name, loc in agents.AGENTS.items():
        config, folder = loc()
        if name not in found:
            print(f"-        {name}: not detected ({config} does not exist)")
        elif (folder / "SKILL.md").exists() and (folder / agents.MARKER).exists():
            ok(f"{name}: skill installed at {folder}")
        else:
            bad(f"{name}: skill not installed at {folder}: run `carbon install-skill --agent {name}`")

    agent = procs.detect_agent()
    ok(f"agent for this process: {agent['name']} (pid {agent['pid']}, via {agent['how']})")
    try:
        sess = tokens.resolve_session(str(agent["pid"]), os.getcwd())
    except Exception:
        sess = None
    if sess:
        ok(f"token session: {sess['harness']} via {sess['how']}")
    else:
        print("-        token session: none found (normal outside an agent session)")

    if measure:
        problems += _measure()

    if problems:
        print(f"\n{problems} problem(s) found.")
        return 1
    print("\nAll checks passed.")
    return 0


def _measure() -> int:
    from . import end, report, start

    old = os.environ.get("CARBON_PARENT_PID")
    os.environ["CARBON_PARENT_PID"] = str(os.getpid())
    try:
        print("...      measuring for 12 s")
        sys.stdout.flush()
        run = start.launch(LABEL, quiet=True)
        rundir = paths.run_dir(run["id"])
        time.sleep(12)
        end.stop(run)
        st = runs.status(run["id"])
        f = report.figures(run["id"])
        if f is None:
            print(f"PROBLEM  test measurement saved no sample; see {rundir / 'monitor.log'}")
            return 1
        cpu, gpu = st.get("cpu_method") or "unknown", st.get("gpu_method") or "unknown"
        kind = "measured" if cpu in start.MEASURED_CPU else "ESTIMATE"
        print(f"ok       test measurement: {f['energy'] * 1000:.3f} Wh; CPU {cpu} ({kind}); GPU {gpu}")
        db.delete_run(run["id"])
        shutil.rmtree(rundir, ignore_errors=True)
        return 0
    except paths.Failure as exc:
        print(f"PROBLEM  test measurement failed:\n{exc}")
        return 1
    finally:
        if old is None:
            os.environ.pop("CARBON_PARENT_PID", None)
        else:
            os.environ["CARBON_PARENT_PID"] = old
