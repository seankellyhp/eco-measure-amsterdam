# Carbon skill: workshop MVP plan

This is an implementation brief. It is written so that someone with no prior
context on this repository can carry it out step by step.

## 1. Goal

A skill plus a Python program that lets a workshop participant track, and then
reduce, the footprint of AI-assisted coding. It integrates CodeCarbon (this
machine, measured) and EcoLogits (provider inference, estimated) with the
participant's coding agent.

It must:

- install and run with **uv** only, on **Linux, macOS and Windows** (native, no WSL);
- work in **Claude Code first, then Codex CLI**, with a clear path to add other agents;
- install from a **clone of this repository** (the workshop route) or straight from GitHub.

## 2. Ground rules for the implementer

- All work is inside `carbon_skill/`, plus one CI file at
  `.github/workflows/carbon-skill.yml`. Do not touch `notebooks/`, the root
  `pyproject.toml` or the root `uv.lock`.
- Work on a branch named `carbon-python-port`. Never push. Commit only if the
  user has asked for commits, one commit per step in section 9.
- No new runtime dependencies beyond those listed in section 4.
- Keep the report text byte-for-byte the same as today except where this plan
  says otherwise. The wording was chosen carefully (scopes are never summed,
  estimates are labelled).
- Do not change how tokens are counted (`tokens.py` readers) or how the
  EcoLogits estimate is computed (`provider_impacts.py`). Move them, fix
  imports, nothing more.
- The development machine is Linux. macOS and Windows are verified only by CI
  and by the manual checklist in section 8. Say plainly in the final report
  which of those were actually run.
- Never run a `sudo` command. Never run the raw `codecarbon` CLI.
- When a fact in this plan is marked **VERIFY**, check it before relying on
  it, and record what was found in `carbon_skill/NOTES.md`.

## 3. Current state (what exists today)

```
carbon_skill/
  README.md, install.sh
  carbon/
    SKILL.md (421 lines), pyproject.toml, uv.lock, .python-version
    scripts/
      common.sh carbon_start.sh carbon_end.sh carbon_report.sh watchdog.sh   bash
      locate.py tokens.py provider_impacts.py sections.py report.py report_live.py
```

Keep (portable Python, sound logic):

- `tokens.py`: billed token counts from the session transcript, deduplicated per message; session resolution in three tiers.
- `provider_impacts.py`: per-request EcoLogits estimate with ranges and model stand-ins.
- `locate.py`: grid detection with a visible fallback instead of codecarbon's silent Quebec default.
- `report.py`, `sections.py`: the three-block report and its closing instruction.

Replace:

| Problem | Where | Effect |
|---|---|---|
| Orchestration is bash with Unix process semantics (`setsid`, SIGTERM, `/proc`, `ps -o`, `.venv/bin`) | `install.sh`, `scripts/*.sh` | Native Windows cannot work; the installer refuses it |
| codecarbon is driven as a CLI subprocess, stopped by signal, read back by regex over `monitor.log` | `carbon_start.sh`, `report_live.py`, `common.sh` | Fragile; a clean stop is impossible from bash on Windows |
| Not a Python package: loose scripts, hand-rolled installer, a shim hiding the codecarbon CLI | whole layout | Hard to install, test or extend |
| Installs only to `~/.claude/skills`; reads only Claude Code and pi transcripts | `install.sh`, `tokens.py` | Codex users get nothing |
| No run comparison or baseline subtraction | reports | The "reduce" half is left to the agent's prose |
| `SKILL.md` is 421 lines, all loaded when the skill triggers | `SKILL.md` | A real token cost in a footprint tool |
| Measurements live inside the skill folder | `runs/` | Uninstalling deletes them |
| Labels are not validated | `carbon_start.sh` | A run folder literally named `--project-name` exists on the author's machine |
| No tests | repository | Cross-platform claims are unverified |

Facts checked on the author's machine (codecarbon 3.3.2, Claude Code on Linux):

- Claude Code exports `CLAUDE_CODE_SESSION_ID` and `CLAUDE_PID` to tool-call
  processes. `CLAUDE_PID` is the pid of the `claude` process itself.
- `psutil` and `platformdirs` are importable; `psutil` is a codecarbon dependency.
- `OfflineEmissionsTracker.__init__` and `.stop()` are decorated
  `@suppress(Exception)`: a failure is swallowed and leaves a half-built
  object. The code must check for this (section 5.4).
- `tracker.flush()` is public: it takes a fresh reading and appends a
  cumulative row to `emissions.csv` without stopping. Rows of one tracker share a `run_id`.
- The chosen CPU and GPU method is **not** stored on the tracker. It is only
  logged once: `CPU Tracking Method: <x>` / `GPU Tracking Method: <x>`
  (`codecarbon/core/resource_tracker.py`). Values include `RAPL`, `cpu_load`,
  `Power Gadget`, `Windows EMI`, `PowerMetrics`, `TDP constant`,
  `global constant`, `pynvml`, `amdsmi`, `Unspecified`.
- A `.codecarbon.config` in the home or working directory is read by
  codecarbon and can change behaviour; explicit constructor arguments win.

## 4. Target layout

```
carbon_skill/
  pyproject.toml            moved up from carbon/; see below
  uv.lock                   regenerated with `uv lock`
  README.md                 rewritten (step 8)
  workshop_mvp.md           this file
  NOTES.md                  findings for every VERIFY item
  src/carbon_skill/
    __init__.py             __version__
    __main__.py             python -m carbon_skill -> cli.main()
    cli.py                  argparse; subcommands and aliases
    paths.py                data dir, run dirs, label validation
    procs.py                psutil helpers: agent detection, liveness, detach
    runs.py                 run.json / status.json read and write, orphan sweep
    monitor.py              the detached monitor process
    start.py end.py         command implementations
    report.py               one report path for live and finished runs
    compare.py              carbon compare
    agents.py               skill-folder registry; install-skill
    doctor.py               carbon doctor
    locate.py tokens.py provider_impacts.py sections.py     moved from scripts/
    skill/
      SKILL.md              template, about 80 lines (step 8)
      reference/methodology.md  tokens.md  platforms.md
  tests/
    fixtures/               small, hand-made transcripts and CSVs
    test_*.py
.github/workflows/carbon-skill.yml
```

Deleted at the end of step 3: `install.sh`, `carbon/` (all of it),
`report_live.py`.

`pyproject.toml`:

```toml
[project]
name = "carbon-skill"
version = "0.3.0"
requires-python = ">=3.12"
dependencies = [
    "codecarbon==3.3.2",
    "ecologits==0.11.3",
    "psutil>=5.9",
    "platformdirs>=4",
]

[project.scripts]
carbon = "carbon_skill.cli:main"
carbon_start = "carbon_skill.cli:main_start"
carbon_end = "carbon_skill.cli:main_end"
carbon_report = "carbon_skill.cli:main_report"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/carbon_skill"]
```

The `skill/` folder must ship inside the wheel (it is inside the package, so
hatchling includes it; confirm with `uv build` and by listing the wheel).
`locate.py` imports `requests` and `pycountry`, which codecarbon already
depends on. **VERIFY** they are present after `uv sync`; if not, add them.

Moved modules currently use flat imports (`import sections`, `import tokens`,
`import provider_impacts`). Change these to relative imports.

## 5. Design

### 5.1 Commands

```
carbon start  [label]            begin tracking; returns within a few seconds
carbon end    [label]            stop, then print the report
carbon report [label]            report for a past or live run
carbon compare A B               two runs side by side, with deltas
carbon compare --baseline I T    T with idle run I subtracted
carbon list                      runs, newest first, with state
carbon install-skill [--agent claude-code|codex|all] [--remove]
carbon doctor [--no-measure]
carbon _monitor <rundir>         internal; not shown in --help
```

- `label` defaults to `default` for `start`, and to the most recently started
  run (`<data>/runs/.last`) for `end` and `report`.
- `carbon_start`, `carbon_end`, `carbon_report` are aliases for the first three.
- Exit codes: 0 success, 1 expected failure with a message on stderr, 2 usage error.
- All output is plain ASCII, no colour, so it survives every terminal and
  every agent's output capture. On Windows set stdout and stderr to UTF-8 with
  `errors="replace"` at start-up.

### 5.2 Paths and labels (`paths.py`)

- Data root: `CARBON_RUN_ROOT` if set, else
  `platformdirs.user_data_path("carbon-skill") / "runs"`.
- Run dir: `<root>/<label>/`.
- A label must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`. Anything else is a
  usage error with a clear message. This also rejects labels that start with `-`.
- Starting a label that already has a finished run replaces it: the folder is
  emptied first and `carbon start` prints `Replacing the previous '<label>' run.`

### 5.3 Run folder contract

| File | Written by | Content |
|---|---|---|
| `run.json` | `carbon start`, once | `label`, `measure_secs`, `grid` (`country`, `region`, `description`), `agent` (`pid`, `create_time`, `name`, `how`), `cwd`, `version` |
| `session.json` | `carbon start`, once | what `tokens.resolve_session` returns; absent if not identified |
| `status.json` | the monitor, atomically | `state` (`starting`, `running`, `stopped`, `failed`), `pid`, `create_time`, `started_at`, `ended_at`, `stopped_by`, `cpu_method`, `gpu_method`, `last_flush_at`, `error` |
| `emissions.csv` | codecarbon | one cumulative row per flush; last row is current |
| `monitor.log` | the monitor's stdout and stderr | codecarbon's log |
| `stop` | `carbon end` or the sweep | empty sentinel; its text, if any, is the stop reason |

"Atomically" means write `status.json.tmp` then `os.replace`. Timestamps are
ISO-8601 with offset, seconds precision
(`datetime.now().astimezone().isoformat(timespec="seconds")`).

`sections.py` currently reads `started_at`, `ended_at` and `session.json` as
separate files. Change it to take the values from `status.json` and
`session.json`.

### 5.4 The monitor (`monitor.py`)

Started as `[sys.executable, "-m", "carbon_skill", "_monitor", rundir]`.

1. Read `run.json`. Write `status.json` with `state: starting`, own pid and
   `psutil.Process().create_time()`.
2. Attach a `logging.Handler` to codecarbon's logger that captures the
   `CPU Tracking Method:` and `GPU Tracking Method:` lines. **VERIFY** the
   logger name (`codecarbon.external.logger`). Fall back to scanning
   `monitor.log` after start if the handler captured nothing; then `unknown`.
3. Build the tracker with explicit arguments so a stray `.codecarbon.config`
   cannot change it:
   `OfflineEmissionsTracker(project_name=label, country_iso_code=..., region=... or None, measure_power_secs=..., output_dir=rundir, output_file="emissions.csv", save_to_file=True, save_to_api=False, tracking_mode="machine", log_level="info", allow_multiple_runs=True)`.
   **VERIFY** each keyword against the installed signature.
4. Call `tracker.start()`. Because errors are suppressed, check that the
   tracker actually started (`getattr(tracker, "_start_time", None) is not None`).
   If not: `state: failed`, `error` set to the last lines of the log, exit 1.
5. Write `state: running` with `started_at` and the two methods.
6. Loop once per second until one of:
   - the `stop` file exists (`stopped_by` = its text, or `carbon end`);
   - the bound agent is gone (`stopped_by` = `agent <name> (pid N) exited`);
   - SIGTERM, SIGINT or, on Windows, SIGBREAK was received (`stopped_by` = `signal`).

   Every `measure_secs` seconds inside the loop: `tracker.flush()`, then update
   `last_flush_at` in `status.json`.
7. On exit: `tracker.stop()`, check `emissions.csv` exists and is non-empty,
   write `state: stopped`, `ended_at`, `stopped_by`. Remove the `stop` file.

Because the monitor flushes regularly, a hard-killed monitor loses at most one
interval instead of the whole run.

The agent check uses pid **and** creation time, so a recycled pid is not
mistaken for the agent: alive means `psutil.pid_exists(pid)` and
`abs(psutil.Process(pid).create_time() - recorded) < 1.0`.

### 5.5 Processes (`procs.py`)

Agent detection, in order; record which was used in `run.json` as `how`:

1. `CARBON_PARENT_PID` (explicit override).
2. `CLAUDE_PID`, if that process exists.
3. Walk parents with psutil from the current process and take the first whose
   lower-cased name, without `.exe`, is not in the skip set: `bash sh zsh fish
   dash ksh tcsh csh cmd powershell pwsh conhost env timeout nohup script
   login sudo setsid uv uvx python python3 carbon carbon_start`. If the walk
   reaches the top, use the last process seen.

**VERIFY** on Windows (manual checklist) that route 2 or 3 lands on the Claude
Code process and not on a short-lived wrapper; a wrong binding makes the
monitor stop immediately.

Detached spawn, one function:

- stdin `DEVNULL`; stdout and stderr to the open `monitor.log`; `close_fds=True`;
  `cwd=rundir`. All three standard handles must be redirected. If the monitor
  inherits the tool call's output pipe, the agent's tool call never returns.
- Linux and macOS: `start_new_session=True`.
- Windows: `creationflags = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW`.
  If the spike in step 0 shows the child is killed with its parent's job
  object, add `CREATE_BREAKAWAY_FROM_JOB` and retry without it on
  `PermissionError`.

### 5.6 `carbon start`

1. Orphan sweep (5.8). Validate the label. Refuse if that label is live.
2. Detect the agent. Resolve the grid (turn `locate.main` into a function
   returning country, region, description; keep its cache file at
   `<root>/.location`). Resolve the session with `tokens.resolve_session`.
3. Write `run.json`, `session.json`, `<root>/.last`. Spawn the monitor.
4. Wait up to 30 s for `status.json` to reach `running` or `failed`, or for the
   process to die. On failure print the last 15 lines of `monitor.log` and exit 1.
5. Print the same summary as today: label and pid, run dir, `Grid:`, the grid
   warning when the lookup failed, `CPU: <method> (measured)` or
   `CPU: <method> - ESTIMATE, not measured`, the GPU line, the token session
   line, the auto-stop line, and `Stop with: carbon end <label>`.

Measured CPU methods: `RAPL`, `PowerMetrics`, `Power Gadget`, `Windows EMI`.
Measured GPU methods: `pynvml`, `amdsmi`, `PowerMetrics`. Everything else is
an estimate or none.

CPU advice when estimated, printed to stderr, never executed:

- Linux with `/sys/class/powercap/intel-rapl*`: the existing RAPL instructions,
  copied verbatim from `common.sh` `cpu_power_advice`.
- Linux without it: the existing "no RAPL interface" note.
- macOS: the existing note.
- Windows: `On Windows codecarbon estimates CPU power from CPU load unless
  Intel Power Gadget is installed. Report CPU figures as estimates.`
  **VERIFY** against codecarbon 3.3.2's Windows branch in `resource_tracker.py`
  and adjust the sentence to what the code does.

### 5.7 `carbon end` and `carbon report`

`end`: sweep; if the run is not live, say so and print the report of what was
saved. Otherwise create `stop`, wait up to 40 s for `state: stopped`. If it
does not stop, terminate then kill the monitor with psutil and write
`state: stopped`, `stopped_by: "carbon end (monitor killed - figures as of <last_flush_at>)"`.
Then print the report.

`report`: one code path. Read the last row of the last `run_id` in
`emissions.csv` exactly as `report.py` does now. Differences from today:

- A live run prints the same blocks, including emissions, with the header
  suffix `[LIVE - as of HH:MM:SS; final after carbon end]`.
- If there is no CSV row yet: `No measurement yet - wait <measure_secs> s.` and exit 1.
- Unknown label: list the available runs, exit 1.
- Keep the `(stopped by: ...)` line for any run not ended by `carbon end`.

### 5.8 Orphan sweep (`runs.py`)

Run at the start of `start`, `end`, `report` and `list`. For each run whose
`status.json` says `starting` or `running`:

- monitor not alive (pid plus creation time): set `state: stopped`,
  `stopped_by: "monitor died"`, `ended_at` = `last_flush_at` or now;
- monitor alive but its agent gone: write `stop` with the reason, wait up to
  15 s, then kill as in `end`.

Runs bound to a live agent are never touched.

### 5.9 `carbon compare`

`carbon compare A B` prints one table, B against A, with absolute and
percentage change, for: duration, energy (Wh), CPU, GPU and RAM energy, CO2e
(g), API calls, tokens sent, tokens received, cache hit %, average context,
and the EcoLogits energy and CO2e ranges (low and high compared separately).
Rows whose data is missing in either run show `-`.

`carbon compare --baseline IDLE TASK` prints TASK's machine figures minus
IDLE's scaled to TASK's duration (`idle_energy * task_duration / idle_duration`),
labelled `above idle baseline`. If the two runs used different CPU methods,
print a warning that the comparison mixes a measurement with an estimate.

To do this without duplicating arithmetic, add to `report.py` a function that
returns a run's figures as a dict, and to `tokens.py` and
`provider_impacts.py` small functions returning their totals as data; the
existing `render` functions then format those. Keep rendered text unchanged.

End the output with the same style of bracketed relay instruction that
`sections.footer` prints.

### 5.10 Agents and `carbon install-skill` (`agents.py`)

Registry, one entry per agent:

| Agent | Skill folder | Detected when |
|---|---|---|
| `claude-code` | `$CLAUDE_CONFIG_DIR/skills/carbon`, else `~/.claude/skills/carbon` | the config folder exists |
| `codex` | **VERIFY**: believed `$CODEX_HOME/skills/carbon`, else `~/.codex/skills/carbon` | the config folder exists |

`install-skill`:

- default `--agent all` installs to every detected agent; if none is detected,
  install for `claude-code` and say so;
- copies `skill/SKILL.md` and `skill/reference/` into the folder, replacing
  the placeholder `{{CARBON_CMD}}` with the way to call the program on this
  machine: the bare word `carbon` if `shutil.which("carbon")` resolves to this
  install, otherwise the absolute path of the running executable, with forward
  slashes and quoted if it contains spaces;
- writes a marker file `.installed-by-carbon-skill`; refuses to overwrite a
  `carbon` skill folder without the marker unless `--force`, which moves the
  old folder to `<config>/carbon-skill-backup-<timestamp>` (outside `skills/`);
- old-layout upgrade: if the folder has the marker and a `runs/` subfolder,
  move those runs into the new data root (skip labels that already exist),
  then remove the old `scripts/`, `.venv/`, `pyproject.toml`, `uv.lock`;
- `--remove` deletes only folders carrying the marker. It never deletes the data root;
- prints what it did and `Restart your agent if /carbon is not listed.`

### 5.11 `carbon doctor`

Prints one line per check, `ok` or `PROBLEM: <what to do>`: program version
and path; Python version; codecarbon and ecologits import and versions; data
root writable; whether `carbon` is on PATH (if not: `uv tool update-shell`);
each agent's skill folder and whether the skill is installed there; agent
detected for this process; token session resolvable. Unless `--no-measure`, it
then runs a 12-second measurement under the label `doctor-check`, confirms a
CSV row was written, prints the CPU and GPU method, and deletes the run
without changing `.last`. Exit 1 if any check failed.

### 5.12 Codex support

Two additions: the skill folder (5.10) and a transcript reader in
`tokens.HARNESSES`. Everything below is the author's belief and must be
checked against a real Codex session file and the Codex documentation before
writing code. If Codex is not installed on the development machine, install it
or ask the user for a sample session file; do not write the reader from this
description alone.

- **VERIFY** sessions are JSONL at `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` (default `~/.codex`).
- **VERIFY** usage arrives in `token_count` events with a cumulative total and
  a per-request "last" usage: `input_tokens`, `cached_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`. Use the per-request figures, one
  `Call` per event.
- **VERIFY** OpenAI's `cached_input_tokens` is a subset of `input_tokens`
  (unlike Anthropic's fields). If so: `fresh = input - cached`,
  `cache_read = cached`, `cache_write = 0`. Getting this wrong double-counts.
- **VERIFY** where the model name is recorded (believed a turn-context record)
  and that `provider_impacts.split_model` resolves it to OpenAI.
- **VERIFY** whether a session id or the session's cwd is available: an
  environment variable for tier 1, else a cwd recorded in the session's first
  record for tier 3. Codex paths are by date, not by cwd, so `_slug_dirs`
  does not apply; tier 3 for Codex needs "newest session file whose recorded
  cwd equals ours", labelled `INFERRED`.
- Latency: leave `None` unless a reliable request and response timestamp pair exists.
- Add the Codex process name to nothing; agent detection already takes the
  first non-shell parent. **VERIFY** it lands on the Codex process.

`tokens.py` tier 2 (`/proc/<pid>/fd`) stays Linux-only and is skipped elsewhere.

### 5.13 Reduce-it guidance (in `SKILL.md`)

A short section the agent uses when asked how to lower the footprint. Each
item is an experiment: change one thing, run the same task again, compare.

| Signal in the report | Try |
|---|---|
| Low `Cache hit %` | keep the start of the prompt stable; avoid editing early context mid-session |
| Rising `Average context` | clear or compact between tasks; read narrower file ranges; fewer, smaller tool outputs |
| Large model in `By model` for routine work | a smaller model for searches and mechanical edits |
| Many subagent calls | do small tasks inline |
| High machine energy above idle | check for local jobs (tests, builds, indexing) left running |

The agent must present these as things to test, with `carbon compare` as the
judge, not as measured causes.

### 5.14 `SKILL.md` and reference files

`SKILL.md`, about 80 lines, contains only: the frontmatter (keep the existing
description and triggers, add `carbon compare` and "reduce"), the two-scope
diagram, the commands with `{{CARBON_CMD}}`, "never run the codecarbon CLI
directly", the relay-verbatim rule, the never-sum and never-divide rules, the
two honesty caveats (whole machine; measured versus estimated CPU, never run
sudo), the reduce-it table, and one line per reference file saying when to
open it.

Move the rest of today's `SKILL.md`, edited for the new design, into:

- `reference/methodology.md`: the EcoLogits section and "Read the report honestly";
- `reference/tokens.md`: token accounting, session identification, adding a harness;
- `reference/platforms.md`: per-OS support table, grid, lifecycle, run folder contract, environment variables.

Environment variables to keep working: `CARBON_RUN_ROOT`, `CARBON_COUNTRY`,
`CARBON_REGION`, `CARBON_MEASURE_SECS`, `CARBON_GEO_TIMEOUT`,
`CARBON_PARENT_PID`, `CARBON_SESSION_TRANSCRIPT`, `CARBON_SESSION_HARNESS`,
`CARBON_ECOLOGITS_ZONE`. `CARBON_WATCHDOG_POLL` is dropped.

## 6. Installation routes (for the README)

`uv tool install` puts a Python program in its own private environment and its
commands on PATH, on every OS.

```
# A. From a clone (the workshop route)
git clone https://github.com/seankellyhp/eco-measure-amsterdam
cd eco-measure-amsterdam
uv tool install ./carbon_skill
carbon install-skill
carbon doctor

# B. Straight from GitHub
uv tool install "git+https://github.com/seankellyhp/eco-measure-amsterdam#subdirectory=carbon_skill"
carbon install-skill

# C. From a clone, nothing installed on PATH
uv run --project carbon_skill carbon install-skill
uv run --project carbon_skill carbon start
```

- If `carbon` is not found after A or B: `uv tool update-shell`, then open a new terminal.
- Update: `git pull`, `uv tool install --reinstall ./carbon_skill`, `carbon install-skill`.
- Uninstall: `carbon install-skill --remove`, `uv tool uninstall carbon-skill`.
- Upgrading from the bash version: `uv tool install` refuses to overwrite the
  old `~/.local/bin/carbon_start`, `carbon_end`, `carbon_report` wrappers.
  Delete those three files first (or pass `--force`). `carbon install-skill`
  then migrates old runs (5.10).

**VERIFY** route C: with `uv run`, the recorded `{{CARBON_CMD}}` must be
`uv run --project "<absolute path>" carbon`, since no executable is on PATH.
Detect this case (the running executable lives inside the project's `.venv`)
and write that form.

## 7. Tests

`uv run --project carbon_skill pytest carbon_skill/tests`. Tests must not need
the network: set `CARBON_COUNTRY=NLD` and `CARBON_RUN_ROOT` to a temp folder.

Unit tests, all platforms:

- `paths`: label validation accepts and rejects the right strings, including `--project-name`, `../x`, empty, 65 characters.
- `tokens`: Claude Code fixture with one message split over three lines counts once; time window filtering; sidechain count; latency from `parentUuid`; pi fixture; Codex fixture (step 6).
- `tokens.resolve_session`: explicit variable; id variable; cwd inference labelled `INFERRED`; nothing found returns `None`.
- `provider_impacts.split_model` and `resolve`: the spellings listed in its docstring; an unknown model is `NOT MODELLED`.
- `report`: a fixture CSV with two `run_id`s reports the last row of the last one; output matches a stored golden text.
- `compare`: deltas and baseline scaling on fixture runs; missing data shows `-`.
- `runs`: atomic status writes; the sweep marks a run whose monitor pid is dead; a run with a live agent is untouched.
- `agents`: install into a temp config folder; placeholder replaced; marker written; refuses to overwrite a foreign folder; `--remove` only removes marked folders; old-layout runs are migrated.
- `locate`: `CARBON_COUNTRY` path; lookup failure falls back to the cache, then to `NLD`, with requests patched to fail.

Integration tests, all platforms, marked `slow`:

- `carbon start t1` returns in under 40 s and its parent can exit; after 12 s `carbon report t1` shows `[LIVE`; `carbon end t1` exits 0, `emissions.csv` has a row, `status.json` is `stopped` with `stopped_by` `carbon end`.
- Agent exit: start with `CARBON_PARENT_PID` set to a helper process, kill the helper, and within 15 s the run is `stopped` with the agent-exited reason.
- Pipe test: run `carbon start` through `subprocess.run(..., capture_output=True, timeout=60)`; it must return while the monitor keeps running. This is the hang guard from 5.5.
- Hard kill: kill the monitor after one flush; `carbon report` still prints figures and the sweep records `monitor died`.
- Starting a live label twice fails with exit 1.

CI, `.github/workflows/carbon-skill.yml`: on push and pull request touching
`carbon_skill/**`; matrix `ubuntu-latest`, `macos-latest`, `windows-latest`;
steps: checkout, `astral-sh/setup-uv`, `uv sync --project carbon_skill`,
pytest including slow tests, then `uv tool install ./carbon_skill` and
`carbon doctor`. Upload each run's `monitor.log` as an artifact on failure.

## 8. Manual checklist (cannot be automated)

CI proves the program works on each OS. It cannot prove that a real agent's
tool runner leaves the detached monitor alive. Someone must run this once per
OS and agent, and the result goes in `NOTES.md`:

1. Install by route A. `carbon doctor` is all `ok`.
2. In the agent: "start carbon tracking". The tool call returns within 40 s.
3. Ask something unrelated, wait a minute, then "how much energy so far?". A `[LIVE` report appears with tokens.
4. "stop carbon tracking". The final report has all three blocks.
5. Start again, then close the agent. Within 15 s `carbon list` in a terminal shows the run stopped with the agent-exited reason.
6. On Windows, repeat 2 to 5 from both Git Bash and PowerShell terminals.

Needed before the workshop: Windows with Claude Code, macOS with Claude Code.
Codex on each OS after step 6.

## 9. Work order

Each step ends with the tests for that step passing on Linux.

| # | Step | Done when |
|---|---|---|
| 0 | **Spike.** A 40-line script: spawn a detached Python child as in 5.5 from a parent whose output is captured through a pipe; the parent returns; the child runs until a stop file appears. Add the CI workflow running only this on all three OSes. | Parent returns and child survives on Linux locally; workflow file ready for the user to push. Record the result in `NOTES.md`. |
| 1 | Package skeleton: `pyproject.toml`, `src/carbon_skill/`, move the six Python modules, fix imports, `cli.py` with stub subcommands, `paths.py`. | `uv tool install ./carbon_skill` then `carbon --help`; `paths` and existing-logic unit tests pass. |
| 2 | `procs.py`, `runs.py`, `monitor.py`. | Running `carbon _monitor` by hand on a prepared run folder produces `emissions.csv` and a correct `status.json`, and stops on the `stop` file. |
| 3 | `start`, `end`, `report`, `list`, the sweep. Delete `install.sh` and `carbon/`. | Integration tests pass; the finished-run report matches the golden text. |
| 4 | `agents.py` (`claude-code` only), `doctor.py`, SKILL.md placeholder substitution with the current long `SKILL.md` adapted minimally. | In a real Claude Code session on Linux, checklist items 1 to 5 pass. |
| 5 | Full test suite and the complete CI workflow. | All tests green locally; the user pushes the branch and CI is green on three OSes, or failures are fixed. **MVP complete here.** |
| 6 | Codex: verify, then skill folder and transcript reader with a fixture. | Tokens and provider blocks appear for a real Codex session. |
| 7 | `compare`, with the data-returning refactor of 5.9. | Compare tests pass; the three renderers' text is unchanged. |
| 8 | Short `SKILL.md`, reference files, rewritten `README.md` with routes A to C, a per-OS measured-versus-estimated table, troubleshooting, and the agent-install instructions. | `SKILL.md` is about 80 lines; every command in the README was run. |

## 10. Out of scope

- Agents other than Claude Code and Codex.
- Per-process energy attribution; the measurement stays whole-machine.
- Publishing to PyPI.
- Any change to token counting or to the EcoLogits calculation.
- Hooks that start tracking automatically.

## 11. Risks

| Risk | Mitigation |
|---|---|
| An agent's tool runner on Windows kills detached children when the call ends | Step 0 spike, `CREATE_BREAKAWAY_FROM_JOB` fallback, manual checklist. If it cannot be solved, fall back to a monitor started by `uv run` in a separate terminal and document it. |
| Agent detection binds to a short-lived wrapper, so the run stops at once | `CLAUDE_PID` first; integration test for agent exit; manual checklist; `CARBON_PARENT_PID` override |
| Codex's log format or skill folder differs from the beliefs in 5.12 | Verify against a real file before coding; fall back to cwd inference labelled `INFERRED`; `CARBON_SESSION_TRANSCRIPT` pins it by hand |
| codecarbon swallows start-up errors | Explicit started check in the monitor; `state: failed` with the log tail |
| `carbon` not on PATH after `uv tool install` | `install-skill` records an absolute path; `doctor` reports it; README names `uv tool update-shell` |
| Windows CPU figures are estimates | Stated by `carbon start` and in the per-OS table, as on macOS |
