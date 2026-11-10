"""Import run folders written before the database (carbon 0.3 and the bash
scripts) into it.

A folder qualifies if it has an emissions.csv. It becomes one stopped run, and
is then moved to `<data root>/imported/<label>/`. Nothing is deleted; a folder
that fails to import stays where it was.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

from . import db, paths

MARKER = ".imported"


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def candidates(root: Path | None = None) -> list[Path]:
    root = root or paths.data_root()
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "emissions.csv").is_file()
                  and not (p / MARKER).exists() and p.name != "imported")


def import_folder(folder: Path) -> int:
    """Import one run folder; return the new run id. Raises on failure, having written nothing."""
    from .monitor import methods_from_log

    with open(folder / "emissions.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if rows:
        last = rows[-1].get("run_id")
        rows = [r for r in rows if r.get("run_id") == last]

    info = _json(folder / "run.json")
    st = _json(folder / "status.json")
    if not st:  # bash era: one small file per fact
        st = {
            "started_at": _text(folder / "started_at"),
            "ended_at": _text(folder / "ended_at"),
            "stopped_by": (_text(folder / "stopped_by") or "carbon end").replace("carbon_end", "carbon end"),
        }
    label = info.get("label") or folder.name
    if not paths.valid_label(label):
        label = "imported"
    grid = info.get("grid") or {}
    agent = info.get("agent") or {}
    first = rows[0] if rows else {}
    methods = methods_from_log(folder / "monitor.log")
    started = st.get("started_at")

    fields = {
        "label": label,
        "state": "stopped",
        "created_at": started or db.now_iso(),
        "started_at": started,
        "ended_at": st.get("ended_at") or st.get("last_flush_at"),
        "stopped_by": st.get("stopped_by") or "imported",
        "error": st.get("error"),
        "last_flush_at": st.get("last_flush_at"),
        "agent_pid": agent.get("pid"),
        "agent_ctime": agent.get("create_time"),
        "agent_name": agent.get("name"),
        "agent_how": agent.get("how"),
        "cwd": info.get("cwd"),
        "measure_secs": float(info.get("measure_secs") or 10.0),
        "grid_country": grid.get("country") or first.get("country_iso_code") or "?",
        "grid_region": grid.get("region") or first.get("region") or None,
        "grid_source": grid.get("description") or "imported from emissions.csv",
        "cpu_method": st.get("cpu_method") or methods.get("CPU"),
        "gpu_method": st.get("gpu_method") or methods.get("GPU"),
        "carbon_version": info.get("version") or "bash",
        **db.static_from_codecarbon(first),
    }
    sess = _json(folder / "session.json") or None

    with db.opened() as conn, db.transaction(conn):
        run_id = db.insert_run(fields, sess, conn=conn)
        for r in rows:
            sample = db.sample_from_codecarbon(r)
            conn.execute(
                f"INSERT INTO sample (run_id, seq, {', '.join(db.SAMPLE_COLUMNS)}) "
                f"VALUES (?, (SELECT coalesce(max(seq), 0) + 1 FROM sample WHERE run_id = ?), "
                f"{', '.join('?' for _ in db.SAMPLE_COLUMNS)})",
                [run_id, run_id, *(sample[c] for c in db.SAMPLE_COLUMNS)],
            )
    return run_id


def _destination(root: Path, label: str) -> Path:
    dest = root / "imported" / label
    n = 2
    while dest.exists():
        dest = root / "imported" / f"{label}-{n}"
        n += 1
    return dest


def import_all(quiet: bool = False) -> list[str]:
    """Import every qualifying folder under the data root. Returns one line per folder."""
    from . import usage

    root = paths.data_root()
    notes = []
    for folder in candidates(root):
        try:
            run_id = import_folder(folder)
        except Exception as exc:
            msg = f"carbon: could not import the old run folder {folder}: {exc!r}"
            print(msg, file=sys.stderr)
            notes.append(msg)
            continue
        try:
            usage.save(run_id)
        except Exception as exc:
            print(f"carbon: imported {folder.name}, but not its token usage: {exc!r}", file=sys.stderr)
        dest = _destination(root, folder.name)
        dest.parent.mkdir(exist_ok=True)
        try:
            shutil.move(str(folder), str(dest))
        except OSError as exc:
            print(f"carbon: imported {folder.name} as @{run_id}, but could not move it: {exc}", file=sys.stderr)
            try:
                (folder / MARKER).write_text(f"@{run_id}\n")  # never import it twice
            except OSError:
                pass
            dest = folder
        msg = f"  imported old run '{folder.name}' as @{run_id} (folder kept in {dest})"
        notes.append(msg)
        if not quiet:
            print(msg)
    try:
        (root / ".last").unlink()  # replaced by the current-session default
    except OSError:
        pass
    return notes
