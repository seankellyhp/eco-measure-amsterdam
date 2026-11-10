"""The run database, `<data root>/carbon.db`: the schema and every SQL statement.

Other modules call the functions here; none of them writes SQL. Units are
CodeCarbon's and EcoLogits' own and are part of the column names.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import paths

VERSION = 1
MIN_SQLITE = (3, 37, 0)  # STRICT tables
LIVE = ("starting", "running")

SCHEMA = """
CREATE TABLE session (
  id            INTEGER PRIMARY KEY,
  harness       TEXT NOT NULL,
  harness_id    TEXT,
  transcript    TEXT NOT NULL,
  how           TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  UNIQUE (harness, transcript)
) STRICT;

-- AUTOINCREMENT: a deleted run's id is never given to a new run, so @<id> stays unambiguous.
CREATE TABLE run (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  label          TEXT NOT NULL,
  session_id     INTEGER REFERENCES session(id),
  state          TEXT NOT NULL CHECK (state IN ('starting','running','stopped','failed')),
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  ended_at       TEXT,
  stopped_by     TEXT,
  error          TEXT,
  monitor_pid    INTEGER,
  monitor_ctime  REAL,
  last_flush_at  TEXT,
  agent_pid      INTEGER,
  agent_ctime    REAL,
  agent_name     TEXT,
  agent_how      TEXT,
  cwd            TEXT,
  measure_secs   REAL NOT NULL,
  grid_country   TEXT NOT NULL,
  grid_region    TEXT,
  grid_source    TEXT NOT NULL,
  cpu_method     TEXT,
  gpu_method     TEXT,
  codecarbon_run_id  TEXT,
  os             TEXT,
  cpu_model      TEXT,
  cpu_count      REAL,
  gpu_model      TEXT,
  gpu_count      REAL,
  ram_total_gb   REAL,
  tracking_mode  TEXT,
  pue            REAL,
  carbon_version     TEXT NOT NULL,
  codecarbon_version TEXT,
  python_version     TEXT,
  usage_saved_at     TEXT,
  usage_note         TEXT,
  ecologits_version  TEXT,
  ecologits_zone     TEXT
) STRICT;
CREATE INDEX run_label ON run (label, id);
CREATE INDEX run_session ON run (session_id, id);

CREATE TABLE sample (
  run_id            INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  seq               INTEGER NOT NULL,
  ts                TEXT NOT NULL,
  duration_s        REAL NOT NULL,
  energy_kwh        REAL NOT NULL,
  cpu_energy_kwh    REAL NOT NULL,
  gpu_energy_kwh    REAL NOT NULL,
  ram_energy_kwh    REAL NOT NULL,
  cpu_power_w       REAL NOT NULL,
  gpu_power_w       REAL NOT NULL,
  ram_power_w       REAL NOT NULL,
  emissions_kg      REAL NOT NULL,
  emissions_rate_kg_s REAL NOT NULL,
  water_l           REAL,
  cpu_util_pct      REAL,
  gpu_util_pct      REAL,
  ram_util_pct      REAL,
  ram_used_gb       REAL,
  PRIMARY KEY (run_id, seq)
) STRICT, WITHOUT ROWID;

CREATE TABLE api_call (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  ts           TEXT NOT NULL,
  model        TEXT NOT NULL,
  fresh        INTEGER NOT NULL,
  cache_read   INTEGER NOT NULL,
  cache_write  INTEGER NOT NULL,
  output       INTEGER NOT NULL,
  thinking     INTEGER NOT NULL,
  sidechain    INTEGER NOT NULL,
  latency_s    REAL,
  UNIQUE (run_id, seq)
) STRICT;

-- One row per request once EcoLogits has looked at it. model_used is NULL and
-- every figure NULL when the request could not be modelled, and `how` says why.
CREATE TABLE provider_estimate (
  call_id         INTEGER PRIMARY KEY REFERENCES api_call(id) ON DELETE CASCADE,
  provider        TEXT NOT NULL,
  model_used      TEXT,
  how             TEXT NOT NULL,
  energy_kwh_low  REAL, energy_kwh_high REAL,
  gwp_kg_low      REAL, gwp_kg_high     REAL,
  adpe_kg_low     REAL, adpe_kg_high    REAL,
  pe_mj_low       REAL, pe_mj_high      REAL,
  wcf_l_low       REAL, wcf_l_high      REAL
) STRICT;

CREATE VIEW run_total AS
  SELECT r.id AS run_id, r.label, r.state, r.started_at, r.ended_at, s.*
  FROM run r JOIN sample s ON s.run_id = r.id
  WHERE s.seq = (SELECT max(seq) FROM sample WHERE run_id = r.id);

CREATE VIEW run_tokens AS
  SELECT run_id, count(*) AS calls, sum(sidechain) AS subagent_calls,
         sum(fresh + cache_read + cache_write) AS sent, sum(output) AS received,
         sum(cache_read) AS cache_read
  FROM api_call GROUP BY run_id;
"""

RUN_COLUMNS = (
    "label", "session_id", "state", "created_at", "started_at", "ended_at", "stopped_by", "error",
    "monitor_pid", "monitor_ctime", "last_flush_at", "agent_pid", "agent_ctime", "agent_name",
    "agent_how", "cwd", "measure_secs", "grid_country", "grid_region", "grid_source", "cpu_method",
    "gpu_method", "codecarbon_run_id", "os", "cpu_model", "cpu_count", "gpu_model", "gpu_count",
    "ram_total_gb", "tracking_mode", "pue", "carbon_version", "codecarbon_version", "python_version",
    "usage_saved_at", "usage_note", "ecologits_version", "ecologits_zone",
)
SAMPLE_COLUMNS = (
    "ts", "duration_s", "energy_kwh", "cpu_energy_kwh", "gpu_energy_kwh", "ram_energy_kwh",
    "cpu_power_w", "gpu_power_w", "ram_power_w", "emissions_kg", "emissions_rate_kg_s", "water_l",
    "cpu_util_pct", "gpu_util_pct", "ram_util_pct", "ram_used_gb",
)
CALL_COLUMNS = (
    "seq", "ts", "model", "fresh", "cache_read", "cache_write", "output", "thinking", "sidechain", "latency_s",
)
ESTIMATE_COLUMNS = (
    "provider", "model_used", "how",
    "energy_kwh_low", "energy_kwh_high", "gwp_kg_low", "gwp_kg_high", "adpe_kg_low", "adpe_kg_high",
    "pe_mj_low", "pe_mj_high", "wcf_l_low", "wcf_l_high",
)

# CodeCarbon's EmissionsData / emissions.csv name -> our column. One mapping for
# the monitor, the import of old CSV files and the CSV export.
SAMPLE_FROM_CC = {
    "timestamp": "ts", "duration": "duration_s", "energy_consumed": "energy_kwh",
    "cpu_energy": "cpu_energy_kwh", "gpu_energy": "gpu_energy_kwh", "ram_energy": "ram_energy_kwh",
    "cpu_power": "cpu_power_w", "gpu_power": "gpu_power_w", "ram_power": "ram_power_w",
    "emissions": "emissions_kg", "emissions_rate": "emissions_rate_kg_s", "water_consumed": "water_l",
    "cpu_utilization_percent": "cpu_util_pct", "gpu_utilization_percent": "gpu_util_pct",
    "ram_utilization_percent": "ram_util_pct", "ram_used_gb": "ram_used_gb",
}
STATIC_FROM_CC = {
    "run_id": "codecarbon_run_id", "os": "os", "cpu_model": "cpu_model", "cpu_count": "cpu_count",
    "gpu_model": "gpu_model", "gpu_count": "gpu_count", "ram_total_size": "ram_total_gb",
    "tracking_mode": "tracking_mode", "pue": "pue", "codecarbon_version": "codecarbon_version",
    "python_version": "python_version",
}
_TEXT = {"ts", "codecarbon_run_id", "os", "cpu_model", "gpu_model", "tracking_mode", "codecarbon_version",
         "python_version"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def path() -> Path:
    return paths.data_root() / "carbon.db"


# --------------------------------------------------------------------------- #
# connection and schema
# --------------------------------------------------------------------------- #


def connect() -> sqlite3.Connection:
    """Open the database, creating or checking its schema.

    Autocommit mode: every write goes through `transaction`, which takes the
    write lock up front (BEGIN IMMEDIATE) so a busy database waits instead of
    failing half way.
    """
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise paths.Failure(
            f"SQLite {sqlite3.sqlite_version} is too old; carbon needs 3.37 or newer. "
            "Reinstall with a uv-managed Python: uv tool install --reinstall --python 3.12 ./carbon_skill"
        )
    conn = sqlite3.connect(path(), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        created = _migrate(conn)
    except BaseException:
        conn.close()
        raise
    if created:
        from . import legacy

        legacy.import_all(quiet=True)
    return conn


def _migrate(conn: sqlite3.Connection) -> bool:
    """Create the schema in a new file. True if it was created just now."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == VERSION:
        return False
    if version > VERSION:
        raise paths.Failure(
            f"{path()} was written by a newer carbon (schema {version}; this program knows {VERSION}). "
            "Update the program: uv tool install --reinstall ./carbon_skill"
        )
    with transaction(conn):
        # Re-read under the write lock: another process may have just created it.
        if conn.execute("PRAGMA user_version").fetchone()[0] != 0:
            return False
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.execute(f"PRAGMA user_version={VERSION}")
    return True


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@contextmanager
def opened() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writing() -> Iterator[sqlite3.Connection]:
    """A short write: open, one transaction, close."""
    with opened() as conn, transaction(conn):
        yield conn


def health() -> tuple[int, str]:
    """(schema version, PRAGMA quick_check result) for `carbon doctor`."""
    with opened() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
    return version, check


def dump() -> Iterator[str]:
    with opened() as conn:
        yield from conn.iterdump()


# --------------------------------------------------------------------------- #
# sessions and runs
# --------------------------------------------------------------------------- #


def _session_id(conn: sqlite3.Connection, sess: dict | None) -> int | None:
    if not sess or not sess.get("transcript"):
        return None
    harness = sess.get("harness") or "claude-code"
    conn.execute(
        "INSERT INTO session (harness, harness_id, transcript, how, first_seen_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (harness, transcript) DO UPDATE SET harness_id = coalesce(excluded.harness_id, harness_id)",
        (harness, sess.get("id"), sess["transcript"], sess.get("how") or "?", now_iso()),
    )
    return conn.execute(
        "SELECT id FROM session WHERE harness = ? AND transcript = ?", (harness, sess["transcript"])
    ).fetchone()[0]


def find_session(sess: dict | None) -> int | None:
    if not sess or not sess.get("transcript"):
        return None
    with opened() as conn:
        row = conn.execute(
            "SELECT id FROM session WHERE harness = ? AND transcript = ?",
            (sess.get("harness") or "claude-code", sess["transcript"]),
        ).fetchone()
    return row[0] if row else None


def insert_run(fields: dict, sess: dict | None = None, conn: sqlite3.Connection | None = None) -> int:
    """A new run row (and its session, if new). Returns the run id."""
    cols = [c for c in fields if c in RUN_COLUMNS]

    def go(c: sqlite3.Connection) -> int:
        values = dict(fields)
        values["session_id"] = _session_id(c, sess)
        names = cols + ["session_id"] if "session_id" not in cols else cols
        cur = c.execute(
            f"INSERT INTO run ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
            [values[n] for n in names],
        )
        return cur.lastrowid

    if conn is not None:
        return go(conn)
    with writing() as c:
        return go(c)


def update_run(run_id: int, conn: sqlite3.Connection | None = None, **fields) -> None:
    bad = set(fields) - set(RUN_COLUMNS)
    if bad:
        raise ValueError(f"not run columns: {sorted(bad)}")
    if not fields:
        return
    sql = f"UPDATE run SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?"
    args = [*fields.values(), run_id]
    if conn is not None:
        conn.execute(sql, args)
        return
    with writing() as c:
        c.execute(sql, args)


_RUN_SELECT = (
    "SELECT r.*, s.harness AS s_harness, s.harness_id AS s_id, s.transcript AS s_transcript, s.how AS s_how "
    "FROM run r LEFT JOIN session s ON s.id = r.session_id"
)


def _run_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    sess = None
    if d.pop("s_transcript", None) is not None:
        sess = {"harness": d["s_harness"], "transcript": row["s_transcript"], "how": d["s_how"]}
        if d["s_id"]:
            sess["id"] = d["s_id"]
    for k in ("s_harness", "s_id", "s_how"):
        d.pop(k, None)
    d["session"] = sess
    return d


def get_run(run_id: int) -> dict | None:
    with opened() as conn:
        return _run_dict(conn.execute(f"{_RUN_SELECT} WHERE r.id = ?", (run_id,)).fetchone())


def _one(where: str, args: tuple, live_first: bool) -> dict | None:
    order = "r.state IN ('starting', 'running') DESC, r.id DESC" if live_first else "r.id DESC"
    with opened() as conn:
        row = conn.execute(f"{_RUN_SELECT} WHERE {where} ORDER BY {order} LIMIT 1", args).fetchone()
    return _run_dict(row)


def newest_with_label(label: str) -> dict | None:
    return _one("r.label = ?", (label,), live_first=False)


def newest_in_session(session_id: int) -> dict | None:
    return _one("r.session_id = ?", (session_id,), live_first=True)


def newest_for_agent(pid: int, ctime: float | None) -> dict | None:
    if ctime is None:
        return _one("r.agent_pid = ? AND r.agent_ctime IS NULL", (pid,), live_first=True)
    return _one("r.agent_pid = ? AND abs(r.agent_ctime - ?) < 1.0", (pid, ctime), live_first=True)


def newest_run() -> dict | None:
    return _one("1", (), live_first=True)


def live_runs() -> list[dict]:
    with opened() as conn:
        rows = conn.execute(f"{_RUN_SELECT} WHERE r.state IN ('starting', 'running') ORDER BY r.id").fetchall()
    return [_run_dict(r) for r in rows]


def live_with_label(label: str) -> list[dict]:
    with opened() as conn:
        rows = conn.execute(
            f"{_RUN_SELECT} WHERE r.label = ? AND r.state IN ('starting', 'running') ORDER BY r.id", (label,)
        ).fetchall()
    return [_run_dict(r) for r in rows]


def runs_needing_usage() -> list[int]:
    """Stopped runs whose tokens and estimates were never saved or ruled out."""
    with opened() as conn:
        rows = conn.execute(
            "SELECT id FROM run WHERE state = 'stopped' AND started_at IS NOT NULL "
            "AND usage_saved_at IS NULL AND usage_note IS NULL ORDER BY id"
        ).fetchall()
    return [r[0] for r in rows]


def count_label(label: str) -> int:
    with opened() as conn:
        return conn.execute("SELECT count(*) FROM run WHERE label = ?", (label,)).fetchone()[0]


def delete_run(run_id: int) -> None:
    with writing() as conn:
        conn.execute("DELETE FROM run WHERE id = ?", (run_id,))


def list_runs(label: str | None = None, session_id: int | None = None,
              agent: tuple[int, float | None] | None = None, limit: int = 0) -> list[dict]:
    """Runs newest first with their machine and token totals (None where absent).

    `session_id` and `agent` together mean "this session": either matches.
    """
    where, args = [], []
    if label:
        where.append("r.label = ?")
        args.append(label)
    mine = []
    if session_id is not None:
        mine.append("r.session_id = ?")
        args.append(session_id)
    if agent is not None:
        if agent[1] is None:
            mine.append("(r.agent_pid = ? AND r.agent_ctime IS NULL)")
            args.append(agent[0])
        else:
            mine.append("(r.agent_pid = ? AND abs(r.agent_ctime - ?) < 1.0)")
            args += [agent[0], agent[1]]
    if mine:
        where.append("(" + " OR ".join(mine) + ")")
    sql = (
        "SELECT r.id, r.label, r.state, r.started_at, r.ended_at, r.usage_saved_at, "
        "t.duration_s, t.energy_kwh, t.emissions_kg, k.calls, k.sent "
        "FROM run r LEFT JOIN run_total t ON t.run_id = r.id "
        "LEFT JOIN run_tokens k ON k.run_id = r.id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.id DESC"
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    with opened() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


# --------------------------------------------------------------------------- #
# samples
# --------------------------------------------------------------------------- #


def _num(value):
    """A number from an EmissionsData value or a CSV cell; None if empty."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts(value) -> str | None:
    """CodeCarbon writes local time without an offset; store it with one."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone().isoformat(timespec="seconds")
    except ValueError:
        return str(value)


def sample_from_codecarbon(values: dict) -> dict:
    out = {}
    for cc, col in SAMPLE_FROM_CC.items():
        v = values.get(cc)
        out[col] = _ts(v) if col == "ts" else _num(v)
    for col in SAMPLE_COLUMNS[1:12]:  # NOT NULL figures
        if out[col] is None:
            out[col] = 0.0
    if out["ts"] is None:
        out["ts"] = now_iso()
    return out


def static_from_codecarbon(values: dict) -> dict:
    out = {}
    for cc, col in STATIC_FROM_CC.items():
        v = values.get(cc)
        if col in _TEXT:
            out[col] = None if v is None or v == "" else str(v)
        else:
            out[col] = _num(v)
    return out


def add_sample(conn: sqlite3.Connection, run_id: int, sample: dict, static: dict | None = None) -> int:
    """One sample row with the next seq, in one transaction with last_flush_at
    and (first time only) the run's static columns. Returns the seq."""
    with transaction(conn):
        seq = conn.execute("SELECT coalesce(max(seq), 0) + 1 FROM sample WHERE run_id = ?", (run_id,)).fetchone()[0]
        conn.execute(
            f"INSERT INTO sample (run_id, seq, {', '.join(SAMPLE_COLUMNS)}) "
            f"VALUES (?, ?, {', '.join('?' for _ in SAMPLE_COLUMNS)})",
            [run_id, seq, *(sample[c] for c in SAMPLE_COLUMNS)],
        )
        fields = {"last_flush_at": sample["ts"]}
        if static:
            fields.update(static)
        update_run(run_id, conn=conn, **fields)
    return seq


def last_sample(run_id: int) -> tuple[dict, int] | None:
    """The run's last (cumulative) sample, and how many samples it has."""
    with opened() as conn:
        row = conn.execute(
            "SELECT *, (SELECT count(*) FROM sample WHERE run_id = ?) AS n FROM sample "
            "WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id, run_id),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    return d, d.pop("n")


def samples(run_id: int) -> list[dict]:
    with opened() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sample WHERE run_id = ? ORDER BY seq", (run_id,))]


# --------------------------------------------------------------------------- #
# tokens and estimates
# --------------------------------------------------------------------------- #


def save_usage(run_id: int, calls: list[dict], estimates: list[dict | None], fields: dict) -> None:
    """Replace the run's calls and estimates and set the usage columns, atomically.

    `estimates[i]` belongs to `calls[i]`; None stores no estimate for it.
    """
    with writing() as conn:
        conn.execute("DELETE FROM api_call WHERE run_id = ?", (run_id,))
        for call, est in zip(calls, estimates):
            cur = conn.execute(
                f"INSERT INTO api_call (run_id, {', '.join(CALL_COLUMNS)}) "
                f"VALUES (?, {', '.join('?' for _ in CALL_COLUMNS)})",
                [run_id, *(call[c] for c in CALL_COLUMNS)],
            )
            if est is not None:
                conn.execute(
                    f"INSERT INTO provider_estimate (call_id, {', '.join(ESTIMATE_COLUMNS)}) "
                    f"VALUES (?, {', '.join('?' for _ in ESTIMATE_COLUMNS)})",
                    [cur.lastrowid, *(est.get(c) for c in ESTIMATE_COLUMNS)],
                )
        update_run(run_id, conn=conn, **fields)


def load_usage(run_id: int) -> list[dict]:
    """The run's calls in transcript order, each with its estimate columns
    (`est_provider` is NULL when it has none)."""
    est = ", ".join(f"e.{c} AS est_{c}" for c in ESTIMATE_COLUMNS)
    with opened() as conn:
        rows = conn.execute(
            f"SELECT a.*, {est} FROM api_call a LEFT JOIN provider_estimate e ON e.call_id = a.id "
            "WHERE a.run_id = ? ORDER BY a.seq",
            (run_id,),
        ).fetchall()
    return [dict(r) for r in rows]
