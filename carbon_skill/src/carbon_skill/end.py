"""carbon end, carbon report, carbon list and carbon delete."""

from __future__ import annotations

import shutil
import sys

from . import db, paths, report, runs


def stop(run: dict) -> bool:
    """Stop a live run and save its usage. Returns False if it was not live."""
    if not runs.is_live(run):
        return False
    runs.request_stop(run)
    if not runs.wait_stopped(run, 40):
        runs.force_stop(run, "carbon end")
    from . import usage

    usage.save(run["id"])
    return True


def command_end(ref: str | None) -> int:
    runs.sweep()
    run = runs.find(ref)
    if stop(run):
        print(f"Stopped '{run['label']}'.")
        print()
    else:
        print(f"'{run['label']}' is not running; reporting what was saved.", file=sys.stderr)
    sys.stdout.flush()
    return _print_report(run["id"])


def command_report(ref: str | None) -> int:
    runs.sweep()
    run = runs.find(ref)
    return _print_report(run["id"])


def _print_report(run_id: int) -> int:
    run = runs.status(run_id)
    live = runs.is_live(run)
    lines = report.render(run, live)
    if lines is None:
        if live:
            print(f"No measurement yet - wait {run.get('measure_secs') or 10:g} s.", file=sys.stderr)
        else:
            print(f"No measurement was saved for {runs.name(run)}.", file=sys.stderr)
            if run.get("error"):
                print(run["error"], file=sys.stderr)
        return 1
    stopped_by = run.get("stopped_by")
    if not live and stopped_by and stopped_by != "carbon end":
        print(f"(stopped by: {stopped_by})")
    print("\n".join(lines))
    return 0


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #

LIST_FOOTER = [
    "  [Relay the table above verbatim, in a code block, and stop. Do not",
    "   summarise, reformat, recompute or add assumptions of your own. Energy",
    "   and CO2e are WHOLE-MACHINE measurements. For one run's full report,",
    "   including its EcoLogits estimate: carbon report @<id>]",
]


def _started(iso: str | None) -> str:
    return (iso or "-")[:19].replace("T", " ")


def _or_dash(value, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def command_list(session_only: bool = False, label: str | None = None, n: int = 20) -> int:
    runs.sweep()
    if label:
        paths.check_label(label)
    if n < 0:
        raise paths.UsageError("-n must be 0 (all) or more")
    sid = agent = None
    if session_only:
        here_agent, sess, _ = runs.here()
        sid = db.find_session(sess)
        agent = (here_agent["pid"], here_agent.get("create_time"))
    rows = db.list_runs(label=label, session_id=sid, agent=agent, limit=n)
    if not rows:
        where = " in this session" if session_only else ""
        print(f"No runs{where}{f' labelled {label!r}' if label else ''} in {db.path()}")
        return 0
    print(f"  {'id':>4}  {'label':<16} {'state':<8} {'started':<19}  {'duration':>8} "
          f"{'energy Wh':>10} {'CO2e g':>9} {'calls':>6} {'tokens sent':>12}")
    for r in rows:
        dur = report.hms(r["duration_s"]) if r["duration_s"] is not None else "-"
        energy = None if r["energy_kwh"] is None else r["energy_kwh"] * 1000
        co2 = None if r["emissions_kg"] is None else r["emissions_kg"] * 1000
        saved = r["usage_saved_at"] is not None
        print(
            f"  {r['id']:>4}  {r['label'][:16]:<16} {r['state']:<8} {_started(r['started_at']):<19}  {dur:>8} "
            f"{_or_dash(energy, ',.3f'):>10} {_or_dash(co2, ',.3f'):>9} "
            f"{_or_dash(r['calls'] or 0 if saved else None, ',d'):>6} "
            f"{_or_dash(r['sent'] or 0 if saved else None, ',d'):>12}"
        )
    print()
    print("\n".join(LIST_FOOTER))
    return 0


def command_delete(ref: str) -> int:
    runs.sweep()
    run = runs.find(ref)
    if runs.is_live(run):
        raise paths.Failure(f"Run {runs.name(run)} is still running. Stop it first: carbon end @{run['id']}")
    db.delete_run(run["id"])
    shutil.rmtree(paths.run_dir(run["id"]), ignore_errors=True)
    print(f"Deleted run {runs.name(run)}.")
    if not ref.startswith("@"):
        left = db.count_label(run["label"])
        if left:
            print(f"{left} older run(s) labelled '{run['label']}' remain. See: carbon list --label {run['label']}")
    return 0
