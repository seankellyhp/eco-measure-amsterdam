# Implementation notes: VERIFY items

Checked on Linux (Ubuntu, kernel 6.8), codecarbon 3.3.2, ecologits 0.11.3,
uv 0.9.9, Claude Code, on 2026-11-10.

## Done and verified here

| Item | Finding |
|---|---|
| `requests`, `pycountry` after `uv sync` (4) | Present as codecarbon dependencies; not added. |
| Codecarbon logger name (5.4) | `logging.getLogger("codecarbon")` (`codecarbon/external/logger.py`), not `codecarbon.external.logger`. The methods arrive as one multi-line INFO message ("The below tracking methods have been set up: ... CPU Tracking Method: X ... GPU Tracking Method: Y"); the handler regex picks both out of it. Captured `RAPL` / `pynvml` on this machine. |
| `OfflineEmissionsTracker` keywords (5.4) | `project_name`, `measure_power_secs`, `output_dir`, `output_file`, `save_to_file`, `save_to_api`, `tracking_mode`, `log_level`, `allow_multiple_runs` are on `BaseEmissionsTracker.__init__`; `country_iso_code`, `region` on `OfflineEmissionsTracker.__init__`. All accepted. |
| Started check (5.4) | `tracker._start_time` is set by `start()` (`emissions_tracker.py`); used as the success check. |
| Signals | With `allow_multiple_runs=True` codecarbon installs no signal handlers of its own (only `lock.py` does, when locking), so the monitor's handlers stand. |
| Windows CPU branch (5.6) | `resource_tracker._try_platform_cpu_backend`: on Windows, Windows EMI (needs Windows 11 on bare metal) first, then Intel Power Gadget, else the generic fallback (`cpu_load`, or a TDP constant). The advice sentence names both. Not run on Windows. |
| Codex skill folder (5.10) | Not `$CODEX_HOME/skills`. Official docs (developers.openai.com/codex/skills, now learn.chatgpt.com/docs/build-skills) list user skills at `$HOME/.agents/skills`, repo skills at `.agents/skills`, admin at `/etc/codex/skills`. Registry uses `~/.agents/skills/carbon`, detected when `$CODEX_HOME` or `~/.codex` exists. Not tested with a real Codex install. |
| Route C command (6) | Detected by `sys.prefix` being a `.venv` inside a folder whose `pyproject.toml` names `carbon-skill`; writes `uv run --project "<abs path>" carbon`. Verified by `uv run carbon install-skill` into a temp `CLAUDE_CONFIG_DIR`. |
| Wheel contents (4) | `uv build`: the wheel contains `carbon_skill/skill/SKILL.md` and `skill/reference/*.md`. |
| Agent detection, Claude Code on Linux (5.5) | Route 2 (`CLAUDE_PID`) lands on the `claude` process. |

## Behaviour checked by hand on Linux

- `carbon start` returns in about 1 s, also with output captured through a pipe (the hang guard).
- Live report shows `[LIVE - as of HH:MM:SS; ...]`; `carbon end` stops via the `stop` file, `stopped_by: carbon end`.
- Starting a live label again: exit 1. Label `../x`: exit 2.
- Agent exit: run bound with `CARBON_PARENT_PID` to a `sleep`; killing it stopped the run within the 1 s poll, `stopped_by: agent sleep (pid N) exited`.
- Hard kill (`kill -9` on the monitor): the next command marks it `monitor died`; the report still prints the last flushed row.
- `carbon compare` and `--baseline` on real runs; token and EcoLogits rows filled from a real Claude Code transcript.
- `carbon doctor`: all checks plus the 12 s measurement (RAPL measured, pynvml).

## Not done

- **Step 0 spike (Windows detach)**: skipped at the user's request. In CI the detached monitor starts, survives `carbon start` returning and stops on `carbon end` on `windows-latest`; whether it survives an agent's tool call ending is still untested. `CREATE_BREAKAWAY_FROM_JOB` is not used; if the manual checklist on Windows shows the monitor dying with the tool call, add it in `procs.spawn_detached` (with a retry without it on `PermissionError`).
- **Codex transcript reader (5.12)**: not written. Codex is not installed on this machine and no sample session file was available; the plan forbids writing the reader from the description alone. A Codex session gets energy figures but no Tokens/Provider blocks. Needed: one real `~/.codex/sessions/**/rollout-*.jsonl`.
- **macOS and Windows**: run only in CI (run 42796438779, all three OSes green: tests, `uv tool install`, `install-skill`, `doctor` with its measurement). Not run inside a real agent on either. On Windows the three golden-text tests are skipped (they need `time.tzset`), so the report text is not checked there.
- **Manual checklist (8)**: not run in any agent.
- **`uv tool install ./carbon_skill` (route A)**: not run on this machine, because the old bash wrappers in `~/.local/bin` would collide (see README); covered by CI.
- **Tests**: kept minimal at the user's request (labels, token dedup, `split_model`, sweep, install-skill, one slow start/report/end lifecycle test). The rest of section 7 is not written.

# SQLite storage (sqlite_plan.md)

Checked on Linux, Python 3.12.12 (uv), SQLite 3.50.4, codecarbon 3.3.2,
ecologits 0.11.3, on 2026-11-10.

## VERIFY items

| Item | Finding |
|---|---|
| No `emissions.csv` (5.4) | The tracker is built with `output_methods=[]` plus `output_handlers=[SqliteOutput]`, not `save_to_file=False`: every `save_to_*` argument now raises a DeprecationWarning, and `output_methods=[]` turns all of them off. The lifecycle test asserts no `.csv` and no `.json` exists anywhere under the data root. |
| EcoLogits units (4) | `energy` kWh, `gwp` kgCO2eq, `adpe` kgSbeq, `pe` MJ, `wcf` L; columns are named `_kwh`, `_kg`, `_kg`, `_mj`, `_l`. |
| Other `impacts` fields (4) | `ImpactsOutput` also has `usage` and `embodied` (the same five impacts split by phase), `warnings` and `errors`. The report uses none of them; not stored. |
| WAL on Windows and macOS (5.1) | Verified by CI run 42796438779 (commit 8118b0d, 2026-11-10) on `macos-latest` (SQLite 3.54.1) and `windows-latest` (SQLite 3.49.1): the journal mode is `wal`, two connections write without `database is locked`, and the lifecycle test (monitor writing while `report` reads) passes. Local disks only; synced and network folders are still not supported. |

## Where the code departs from the plan, and why

- **`provider_estimate` has a row for every request**, with `model_used` and all
  figures NULL when it could not be modelled. Without the row the `By model`
  table loses the `how` note (`no provider`, `unregistered`) and the report
  text changes. An unregistered model is not `impacts=None` in EcoLogits but an
  `impacts` object with `errors`, so "has figures" is the test, not "has a row".
- **`api_call.ts` keeps full precision** (`Call.ts.isoformat()`), not seconds:
  the energy chart bins requests by time, and rounding moved points between bins.
- **`run.id` is `AUTOINCREMENT`**, so a deleted run's id is never reused and an
  old `@<id>` cannot silently name a different run. Found by the smoke test.
- **Stored ranges** come back as a `RangeValue` when low and high differ and as
  a plain number when equal, as the plan says. EcoLogits gives a scalar or a
  real interval; an interval with equal ends would render as a scalar.
- **The sweep saves usage**: every command already calls `runs.sweep()`, so it
  is the "any command that meets a stopped run without saved usage" of 5.5.
- **"Inside an agent session" (5.3.1)** means a session found by id or open file,
  an agent found by `CARBON_PARENT_PID` / `CLAUDE_PID`, or a known agent
  (`claude`, `codex`, `pi`: `procs.KNOWN_AGENTS`) among the ancestor processes.
  The last covers an agent with no identifiable session (Codex today), which
  would otherwise fall to rule 3 and take another session's run.
- **A session guessed from the cwd never selects a run** (`runs.exact`): rule 1
  and `list --session` ignore it. The guess is "newest transcript in this
  folder", which can be another session's (two sessions in one folder, or a
  plain terminal in a project folder). Such a run is still found by rule 2, its
  agent process. Cost: after an agent restart (`--resume`) a run whose session
  was only guessed is no longer the default; name it by label or `@<id>`.
- **SQL dump (5.8)**: `iterdump()` leaves out `PRAGMA user_version`, so
  `carbon export --format sql` appends it; without it a restored file read as
  new and carbon failed on `CREATE TABLE`. A version-0 file that already has
  all five tables is adopted (older dumps); one with only some is refused.
- **Import with no recorded end (5.7)**: `ended_at` falls back to the last
  sample's time, so the saved token window does not run to the time of import.
- **Import (5.7)** lives in `legacy.py`. Folders go to `imported/<label>`, or
  `imported/<label>-2` etc. if taken. A folder that imports but cannot be moved
  gets an `.imported` marker so it is never imported twice. `.last` is removed.
- Run folders are named by run id. A pre-database folder whose label was all
  digits and that failed to import could share a name with a new run's folder;
  harmless (only `monitor.log` and `stop` live there) and unlikely.

## Checked by hand on Linux

- Your real data folder: the `default` run imported as @1; `carbon report default`
  is byte-identical to the 0.3 code's output for the same folder (diffed). The
  original folder is in `imported/default/`.
- Inside a Claude Code session: `start`, `end` with no label (this session's run),
  a second run under the same label, `compare @1 @2`, `compare --baseline`,
  `list`, `list --session`, `list --label -n`, `export` (CSV and SQL, to stdout
  and `-o`), `delete`, the `carbon_report` alias, `install-skill`, and `doctor`
  with its 12 s measurement.
- Tests: golden text (from the database, and again with the transcript deleted),
  db, `SqliteOutput`, `usage.save`, labels and `@id`, current-session rules,
  history filters, import, export (including restoring the SQL dump), and the
  slow lifecycle test. 48 pass.
