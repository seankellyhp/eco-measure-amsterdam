"""carbon end, carbon report and carbon list."""

from __future__ import annotations

import sys

from . import paths, report, runs


def stop(label: str) -> bool:
    """Stop a live run. Returns False if it was not live."""
    rundir = paths.data_root() / label
    if not runs.is_live(rundir):
        return False
    runs.request_stop(rundir)
    if not runs.wait_stopped(rundir, 40):
        runs.force_stop(rundir, "carbon end")
    return True


def command_end(label: str | None) -> int:
    label = paths.label_or_last(label)
    runs.sweep()
    rundir = paths.data_root() / label
    if not rundir.is_dir():
        return _unknown(label)
    if stop(label):
        print(f"Stopped '{label}'.")
        print()
    else:
        print(f"'{label}' is not running; reporting what was saved.", file=sys.stderr)
    sys.stdout.flush()
    return _print_report(label)


def command_report(label: str | None) -> int:
    label = paths.label_or_last(label)
    runs.sweep()
    if not (paths.data_root() / label).is_dir():
        return _unknown(label)
    return _print_report(label)


def _unknown(label: str) -> int:
    labels = paths.all_labels()
    print(f"No run named '{label}'. Available runs:", file=sys.stderr)
    print("\n".join(f"  {x}" for x in labels) if labels else "  (none)", file=sys.stderr)
    return 1


def _print_report(label: str) -> int:
    rundir = paths.data_root() / label
    st = runs.status(rundir)
    live = runs.is_live(rundir)
    lines = report.render(label, rundir, live)
    if lines is None:
        secs = runs.run_info(rundir).get("measure_secs", 10)
        if live:
            print(f"No measurement yet - wait {secs:g} s.", file=sys.stderr)
        else:
            print(f"No measurement was saved for '{label}'.", file=sys.stderr)
            if st.get("error"):
                print(st["error"], file=sys.stderr)
        return 1
    stopped_by = st.get("stopped_by")
    if not live and stopped_by and stopped_by != "carbon end":
        print(f"(stopped by: {stopped_by})")
    print("\n".join(lines))
    return 0


def command_list() -> int:
    runs.sweep()
    root = paths.data_root()
    rows = []
    for label in paths.all_labels():
        st = runs.status(root / label)
        state = st.get("state", "?")
        if state in runs.LIVE_STATES and not runs.monitor_alive(st):
            state = "dead"
        rows.append((st.get("started_at") or "", label, state, st.get("stopped_by") or ""))
    if not rows:
        print(f"No runs in {root}")
        return 0
    rows.sort(reverse=True)
    print(f"{'label':<24} {'state':<9} {'started':<26} stopped by")
    for started, label, state, why in rows:
        print(f"{label:<24} {state:<9} {started:<26} {why}")
    return 0
