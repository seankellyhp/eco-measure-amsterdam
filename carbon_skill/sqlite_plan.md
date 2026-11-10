# Carbon skill: SQLite storage plan

This is an implementation brief, in the same style as `workshop_mvp.md`. It
replaces the per-run `emissions.csv` and the three per-run JSON files with one
SQLite database.

## 1. Goal

One database file holds everything the tool records:

- the agent session a run was started from;
- the run itself: label, grid, hardware, measurement method, lifecycle state;
- what CodeCarbon measured, as a time series;
- what the session sent and received (tokens, per request);
- what EcoLogits estimated for those requests.

Why this is better than today:

| Today | Problem | With the database |
|---|---|---|
| `emissions.csv`, one 40-column row per flush | about 30 of the columns (hardware, OS, versions, country) never change within a run, and every report re-reads and re-parses the whole file | static values stored once on the run; a sample row holds only what changes; a report reads one row through an index |
| `run.json`, `status.json`, `session.json` | three files per run, read-modify-write races, nothing can be queried across runs | columns on `run` and `session`, updated in transactions |
| Tokens and EcoLogits figures are recomputed from the transcript on every report | Claude Code deletes old transcripts, after which a finished run loses its Tokens and Provider blocks | saved once when the run ends; a finished run no longer needs the transcript |
| Starting a label deletes the previous run with that label | history is lost; `compare` needs invented labels | every run is kept; `carbon end` still reports only the current session's run, and history is shown on request |

## 2. Ground rules

- **No new dependency.** Use the standard library `sqlite3` module. It is
  compiled into every Python that uv installs, on all three OSes.
- The file is a SQLite database, `carbon.db`. It is binary, not a text `.sql`
  script. `carbon export --format sql` (5.8) writes a text `.sql` dump for
  anyone who wants one.
- Report text stays byte-for-byte the same. Step 0 adds the golden-text test
  that proves it, before anything else changes.
- Token counting (`tokens.py` readers) and the EcoLogits computation
  (`provider_impacts.estimate`) are not changed. Only where their results are
  stored changes.
- No ORM, no migration framework. One `db.py` module owns the schema and every
  SQL statement; the other modules call its functions.
- All work is inside `carbon_skill/`. Work on the current branch. Commit only
  if asked.
- Items marked **VERIFY** are checked before relying on them, and the finding
  is recorded in `NOTES.md`.

## 3. Facts checked (codecarbon 3.3.2, Python 3.12.12 from uv, Linux)

- The bundled SQLite is 3.50.4. `STRICT` tables need 3.37, `RETURNING` 3.35.
- `OfflineEmissionsTracker` accepts `output_handlers=[...]`, a list of
  `codecarbon.output_methods.base_output.BaseOutput` objects, and
  `save_to_file=False`.
- `tracker.flush()` and `tracker.stop()` call `handler.out(total, delta)` on
  each handler (`emissions_tracker._persist_data`). `total` is an
  `EmissionsData` with cumulative figures since `start()`.
- The monitor calls `flush()` and `stop()` from its main thread, so the handler
  can own a `sqlite3` connection without thread problems.
- `EmissionsData` fields: `timestamp, project_name, run_id, experiment_id,
  duration, emissions, emissions_rate, cpu_power, gpu_power, ram_power,
  cpu_energy, gpu_energy, ram_energy, energy_consumed, water_consumed,
  country_name, country_iso_code, region, cloud_provider, cloud_region, os,
  python_version, codecarbon_version, cpu_count, cpu_model, gpu_count,
  gpu_model, longitude, latitude, ram_total_size, tracking_mode,
  cpu_utilization_percent, gpu_utilization_percent, ram_utilization_percent,
  ram_used_gb, on_cloud, pue, wue`.
- `tokens.Call` has no message id: `ts, model, fresh, cache_read, cache_write,
  output, thinking, sidechain, latency`.
- `provider_impacts.Estimate` has `resolved` (the registry model used), `how`
  (exact or stand-in) and `impacts` with `energy, gwp, adpe, pe, wcf`, each a
  number or a `RangeValue` with `min` and `max`.

## 4. Data model

```
session 1 ---- n run 1 ---- n sample          (CodeCarbon, measured)
                     1 ---- n api_call 1 ---- 0..1 provider_estimate
                              (tokens, exact)        (EcoLogits, estimated)
```

The three kinds of figure stay in three tables, matching the three report
blocks. Nothing in the schema adds a CodeCarbon figure to an EcoLogits one.

Conventions: timestamps are ISO-8601 text with offset, seconds precision, as
today. Units are CodeCarbon's and are in the column name (`_kwh`, `_kg`, `_w`,
`_s`). All tables are `STRICT`.

```sql
-- The agent session a run was started from. Several runs can share one.
CREATE TABLE session (
  id            INTEGER PRIMARY KEY,
  harness       TEXT NOT NULL,          -- claude-code, pi, ...
  harness_id    TEXT,                   -- the harness's own session id, if known
  transcript    TEXT NOT NULL,          -- path of the session log
  how           TEXT NOT NULL,          -- how it was identified, e.g. $CLAUDE_CODE_SESSION_ID
  first_seen_at TEXT NOT NULL,
  UNIQUE (harness, transcript)
) STRICT;

-- One tracking run. Static facts are stored here once.
CREATE TABLE run (
  id             INTEGER PRIMARY KEY,
  label          TEXT NOT NULL,
  session_id     INTEGER REFERENCES session(id),   -- NULL if not identified
  -- lifecycle (was status.json)
  state          TEXT NOT NULL CHECK (state IN ('starting','running','stopped','failed')),
  created_at     TEXT NOT NULL,
  started_at     TEXT,
  ended_at       TEXT,
  stopped_by     TEXT,
  error          TEXT,
  monitor_pid    INTEGER,
  monitor_ctime  REAL,
  last_flush_at  TEXT,
  -- binding and settings (was run.json)
  agent_pid      INTEGER,
  agent_ctime    REAL,
  agent_name     TEXT,
  agent_how      TEXT,
  cwd            TEXT,
  measure_secs   REAL NOT NULL,
  grid_country   TEXT NOT NULL,
  grid_region    TEXT,
  grid_source    TEXT NOT NULL,          -- the "Grid:" description
  cpu_method     TEXT,
  gpu_method     TEXT,
  -- static facts from the first CodeCarbon sample
  codecarbon_run_id  TEXT,
  os             TEXT,
  cpu_model      TEXT,
  cpu_count      REAL,
  gpu_model      TEXT,
  gpu_count      REAL,
  ram_total_gb   REAL,
  tracking_mode  TEXT,
  pue            REAL,
  -- versions
  carbon_version     TEXT NOT NULL,
  codecarbon_version TEXT,
  python_version     TEXT,
  -- usage snapshot (5.5)
  usage_saved_at     TEXT,               -- NULL until tokens and estimates are saved
  usage_note         TEXT,               -- why they could not be saved, if so
  ecologits_version  TEXT,
  ecologits_zone     TEXT
) STRICT;
CREATE INDEX run_label ON run (label, id);

-- One row per flush: only the values that change. Energy and emissions are
-- cumulative since the run started, so the last row is the run's total and a
-- lost row loses nothing.
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

-- One billed request of the session, inside the run's time window.
CREATE TABLE api_call (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,         -- transcript order
  ts           TEXT NOT NULL,
  model        TEXT NOT NULL,            -- as the harness recorded it
  fresh        INTEGER NOT NULL,
  cache_read   INTEGER NOT NULL,
  cache_write  INTEGER NOT NULL,
  output       INTEGER NOT NULL,
  thinking     INTEGER NOT NULL,
  sidechain    INTEGER NOT NULL,         -- 1 if made by a subagent
  latency_s    REAL,
  UNIQUE (run_id, seq)
) STRICT;

-- The EcoLogits estimate for one request. Absent if the model is not modelled.
-- Low and high bounds are stored separately; equal when EcoLogits gives one value.
CREATE TABLE provider_estimate (
  call_id         INTEGER PRIMARY KEY REFERENCES api_call(id) ON DELETE CASCADE,
  provider        TEXT NOT NULL,
  model_used      TEXT NOT NULL,         -- registry model computed with
  how             TEXT NOT NULL,         -- exact match, or which stand-in and why
  energy_kwh_low  REAL, energy_kwh_high REAL,
  gwp_kg_low      REAL, gwp_kg_high     REAL,
  adpe_kg_low     REAL, adpe_kg_high    REAL,
  pe_mj_low       REAL, pe_mj_high      REAL,
  wcf_l_low       REAL, wcf_l_high      REAL
) STRICT;

-- Convenience for people querying the file by hand.
CREATE VIEW run_total AS
  SELECT r.id AS run_id, r.label, r.state, r.started_at, r.ended_at, s.*
  FROM run r JOIN sample s ON s.run_id = r.id
  WHERE s.seq = (SELECT max(seq) FROM sample WHERE run_id = r.id);

CREATE VIEW run_tokens AS
  SELECT run_id, count(*) AS calls, sum(sidechain) AS subagent_calls,
         sum(fresh + cache_read + cache_write) AS sent, sum(output) AS received,
         sum(cache_read) AS cache_read
  FROM api_call GROUP BY run_id;
```

**VERIFY** the units EcoLogits uses for `adpe`, `pe` and `wcf` and name the
columns after them. **VERIFY** that an `impacts` object carries no other
top-level figure worth storing.

Deliberately left out: per-task CodeCarbon data (the tool does not use tasks),
`longitude`/`latitude` (not needed, and location data), cloud fields (always
empty in offline machine mode), and the host name.

## 5. Design

### 5.1 The file and how it is opened (`db.py`)

- Path: `<data root>/carbon.db`, so `CARBON_RUN_ROOT` moves it with everything else.
- `db.connect()` opens it and runs:
  `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;`
  WAL lets the monitor write while a report reads. **VERIFY** WAL works on the
  Windows and macOS CI runners.
- Schema version is `PRAGMA user_version`. Version 0 means a new file: create
  the schema above and set it to 1. A version higher than the program knows is
  a `Failure` telling the user to update the program.
- Every write is its own short transaction (`with conn:`). No connection is
  held across a sleep, except the monitor's.
- `doctor` gains one check: the database opens, its version is known, and
  `sqlite3.sqlite_version` is at least 3.37.

### 5.2 Run folders

The database holds data. Two things that are not data stay as files, in
`<data root>/<run id>/`:

- `monitor.log`: CodeCarbon's log, written by the detached process's stdout;
- `stop`: the stop sentinel, unchanged. It is checked every second, and a file
  check keeps working even if the database is busy.

`run.json`, `status.json`, `session.json` and `emissions.csv` are no longer written.

### 5.3 Labels and run ids

- `carbon start [label]` always inserts a new run. It no longer deletes the
  previous run with that label, and no longer prints `Replacing the previous ...`.
- It still refuses if a run with that label is live.
- Wherever a command takes a label, it means the newest run with that label.
  `@<id>` names one run exactly (`carbon report @12`, `carbon compare @12 @15`).
  `@` is not valid in a label, so there is no ambiguity.
- No label: `end` and `report` use the current session's run (5.3.1). The
  `.last` file is dropped.
- History is available on request, never by default (5.3.2).
- New: `carbon delete <label|@id>` removes a stopped run (its rows cascade)
  and its folder. Deleting a label deletes only the newest run with it, and
  says how many older ones remain.

#### 5.3.1 The default run is the current session's

`carbon end` and `carbon report` without a label must act on the run of the
session they are called from, not on whatever was started last on the machine.
Today `.last` is machine-wide, so one agent session can stop another's run.

`runs.current_run()` picks, in order, and records which rule matched:

1. the newest run whose `session_id` is this session's. The session is found
   exactly as `carbon start` finds it (`tokens.resolve_session`), then looked
   up in `session` by harness and transcript;
2. else the newest run bound to the same agent process (`agent_pid` and
   `agent_ctime` equal to `procs.detect_agent()`). This covers a session whose
   transcript could not be identified;
3. else, only when no agent session is detected at all (a plain terminal), the
   newest run on the machine, with one line on stderr:
   `No agent session detected; using the most recent run '<label>' (@<id>).`

Within a rule, a live run is preferred over a stopped one. If rules 1 and 2
find nothing inside an agent session, the command fails with exit 1:
`No run was started in this session. See: carbon list` and does not touch
another session's run. An explicit label or `@id` always overrides this.

`carbon end` prints the report for that one run only, as today. It never
prints other runs.

#### 5.3.2 History on request

`carbon list` (alias `carbon history`) is the only command that shows more
than one run. One line per run, newest first:

```
  id  label     state    started              duration   energy Wh   CO2e g    calls   tokens sent
```

- Machine figures come from `run_total`, token figures from `run_tokens`;
  a run without saved usage shows `-`. EcoLogits figures are not in the table,
  so nothing invites adding the scopes; `carbon report @<id>` shows them.
- Default: every run on the machine. `--session` limits it to the current
  session (rules 1 and 2 above). `--label L` limits it to one label.
  `-n N` shows the newest N (default 20; `-n 0` for all).
- It ends with the same style of bracketed relay instruction as the report.
- The full report of any past run is `carbon report <label|@id>`.

### 5.4 The monitor

- Started as `_monitor <run id>`.
- A small `BaseOutput` subclass, `SqliteOutput`, defined in `monitor.py`:
  `out(total, delta)` inserts one `sample` row with the next `seq`. On the
  first call it also fills the static columns on `run` (`codecarbon_run_id`,
  hardware, versions, `tracking_mode`, `pue`). It updates `last_flush_at` in
  the same transaction.
- The tracker is built with `save_to_file=False, output_handlers=[SqliteOutput(...)]`.
  **VERIFY** no `emissions.csv` appears.
- A failed insert must not kill the monitor: catch `sqlite3.Error` in `out`,
  print it to `monitor.log`, and carry on; the next cumulative row makes up for it.
- State changes (`starting`, `running`, `stopped`, `failed`) are `UPDATE run`
  statements where `runs.update_status` is called today.

### 5.5 Saving tokens and estimates

New module `usage.py`, one function `usage.save(run_id)`:

1. Load the run's calls with `tokens.load(started_at, ended_at, session)`.
2. If the session or transcript is missing, set `usage_note` and return.
3. Compute `provider_impacts.estimate(calls)`.
4. In one transaction: delete the run's `api_call` rows, insert the calls and
   their estimates, set `usage_saved_at`, `ecologits_version`, `ecologits_zone`.

It is called by `carbon end` after the monitor stops, and by any command that
meets a stopped run whose `usage_saved_at` and `usage_note` are both NULL
(a run ended by agent exit or a dead monitor). The monitor itself never
imports EcoLogits.

Reading, in `sections.usage_sections`:

- live run: compute from the transcript in memory, as today; nothing is stored;
- stopped run with `usage_saved_at`: rebuild the `Call` and `Estimate` lists
  from the tables and pass them to the existing `render` functions;
- otherwise: as today when the session is unknown.

`provider_impacts.render` works on `Estimate.impacts` objects. Add the smallest
adapter that lets stored low and high bounds stand in for them, so the
rendered text is identical. The golden test covers this.

### 5.6 Reports and compare

- `report.figures(run_id)` reads the last `sample` row and the `run` row and
  returns the same dict as today (`samples` is `count(*)`).
- `compare._data` reads the same, plus token and provider totals through 5.5.
- `runs.py` keeps its function names (`status`, `update_status`, `is_live`,
  `sweep`, `force_stop`) with database-backed bodies, so `start.py`, `end.py`
  and `doctor.py` change little.

### 5.7 Importing existing runs

On the first open of a new database, and from `install-skill` for bash-era
runs, import every folder under the data root that has an `emissions.csv`:

- `run` from `run.json` and `status.json` (bash-era: `started_at`, `ended_at`,
  `stopped_by` files), state `stopped`;
- `sample` from the rows of the last `run_id` in the CSV;
- `session` from `session.json`; then `usage.save` if the transcript still exists;
- move the folder to `<data root>/imported/<label>/`. Nothing is deleted.

A folder that fails to import is left where it is, with one line on stderr.

### 5.8 Export

`carbon export [label|@id] [--format csv|sql] [-o FILE]`, default CSV to stdout.

- `csv`: one run's samples with CodeCarbon's own `emissions.csv` column names,
  rebuilt from `run` and `sample`, so notebooks and tools that read
  CodeCarbon files keep working.
- `sql`: the whole database as SQL text (`Connection.iterdump()`); the label
  is not accepted with it.

## 6. Tests

Golden first, then per step. No network, temp `CARBON_RUN_ROOT`.

- `report`: fixture rows give the stored golden text, for a run with and
  without saved usage. Written against today's code in step 0.
- `db`: a new file gets the schema and version 1; a newer version is refused;
  two connections can write without `database is locked`.
- `SqliteOutput`: three `out` calls give three rows with rising `seq`, static
  columns filled once; a failing insert does not raise.
- `usage.save`: calls and estimates round-trip; saving twice does not
  duplicate; a missing transcript sets `usage_note`.
- Labels: two runs with one label, the label resolves to the newer, `@id` to
  each; `delete` removes one.
- Current session: with runs from two sessions, `end` and `report` without a
  label pick this session's run even when the other session's is newer; a
  live run wins over a stopped one; inside a session with no run the command
  exits 1 and leaves the other session's run alive; outside any session it
  uses the newest run and says so.
- History: `list` shows every run with totals; `--session`, `--label` and
  `-n` filter it.
- Import: a new-layout folder and a bash-era folder both import and move.
- Export: the CSV has CodeCarbon's header; the SQL dump loads into an empty database.
- Lifecycle (slow): the existing test, plus: no `emissions.csv` exists, and
  the report after `end` still prints the Tokens block when the transcript
  file has been removed.

## 7. Work order

Each step ends with the tests passing on Linux.

| # | Step | Done when |
|---|---|---|
| 0 | Golden-text report test against the current code. | The test passes before any storage change. |
| 1 | `db.py`: connect, pragmas, schema, version. `doctor` check. | `db` tests pass. |
| 2 | `runs.py` on the database; `start`, `end`, `list`, sweep use run ids; labels, `@id` and the current-session default (5.3, 5.3.1). JSON files gone. Samples still come from the CSV. | Lifecycle and current-session tests pass. |
| 3 | `SqliteOutput` in the monitor; `report.figures` and `compare` read `sample`; `emissions.csv` gone. | Golden and lifecycle tests pass; no CSV is written. |
| 4 | `usage.py`, the stored-usage read path. | A finished run reports tokens with its transcript deleted. |
| 5 | Import of existing runs; `carbon delete`; `carbon export`; history columns and filters on `carbon list` (5.3.2). | Import and export tests pass; the author's existing runs appear in `carbon list`. |
| 6 | `SKILL.md` (history only when asked, `@id`, export), `reference/platforms.md` (run folder section becomes the data model), `README.md` ("Where things are", the `emissions.csv` paragraph), `NOTES.md`. | Every command in the README was run. |

## 8. Out of scope

- Any change to token counting or the EcoLogits computation.
- Re-estimating old runs with a newer EcoLogits version.
- Pruning or downsampling old samples (about 100 bytes each; a day of
  tracking at 10 s is under 1 MB).
- Sharing or syncing the database between machines.

## 9. Risks

| Risk | Mitigation |
|---|---|
| `database is locked` when the monitor and a command write together | WAL, `busy_timeout=5000`, short transactions; the two-connection test |
| WAL misbehaves on a network or synced folder (OneDrive home folders on Windows) | The default data folder is local app data; say in `platforms.md` not to point `CARBON_RUN_ROOT` at a synced folder |
| A corrupt database loses every run, where a corrupt CSV lost one | WAL with `synchronous=NORMAL` survives a process kill; `carbon export --format sql` is the backup; `doctor` runs `PRAGMA quick_check` |
| Stored estimates go stale when EcoLogits changes | `ecologits_version` is stored on the run; re-estimating is out of scope but possible, since `api_call` keeps the inputs |
| Report text drifts during the refactor | Golden test from step 0 |
| A system Python with SQLite older than 3.37 | `doctor` check; uv-managed Pythons bundle a recent one |
