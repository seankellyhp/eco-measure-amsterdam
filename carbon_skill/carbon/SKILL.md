---
name: carbon
description: Track the energy use, CO2e emissions and LLM token usage of work done on this machine with the codecarbon CLI, and estimate the provider-side impact of the inference the session paid for with EcoLogits. Use when the user asks to start/stop energy tracking, measure the power or carbon cost of a run, demo or benchmark, or wants a report of compute time, energy, CPU/GPU/RAM breakdown, estimated emissions, water use, how many tokens were sent and received (context size, cache hit rate, prompt efficiency), or what the Claude API calls themselves cost the environment. Triggers include "carbon_start", "carbon_end", "carbon_report", "track energy", "how much power did that use", "emissions of this run", "how many tokens did that use", "is my context clean", "ecologits", "footprint of my Claude usage".
---

# carbon

Two scopes, measured and reported separately, never summed:

```
              CLAUDE CODE SESSION
                      |
        .-------------+-------------.
        |                           |
   THIS MACHINE                PROVIDER
   CodeCarbon                  EcoLogits
   MEASURED                    ESTIMATED
   whole-machine draw          inference for this
   while the run was live      session's output tokens
```

The middle column - the session's own billed token usage - is the shared input
to both, read once from the harness transcript.

**Never invoke `codecarbon` directly.** Always go through the three scripts
below. The bare CLI (`codecarbon monitor`) blocks until Ctrl+C, so an agent that
runs it either hangs or leaves a monitor with no owner, no run directory and no
auto-stop - exactly what this skill exists to prevent. The CLI is deliberately not on PATH, and the copy vendored inside this skill
refuses to run unless one of the three commands below invokes it - if you see
`REFUSED: do not run the codecarbon CLI directly`, use `carbon_start`.

Drives `codecarbon monitor` as a background process so tracking can be started
and stopped across separate turns. Three commands, all in `scripts/`:

```sh
carbon_start  [label]     # begin tracking (default label: "default")
carbon_end    [label]     # stop tracking, then print the report
carbon_report [label]     # print the report for any past or live run
```

The installer puts these three on PATH (`~/.local/bin/`). They are the entire
interface - there is no other supported way to use this skill. If they are not
on PATH (common on macOS), call the scripts in this skill's own directory
directly - normally `bash ~/.claude/skills/carbon/scripts/carbon_start.sh` etc.

If `carbon_start` says the skill is not installed, or `.venv/` is missing, the
skill was copied instead of installed: run `bash carbon_skill/install.sh` from
the repository it came from (see "Installation" below). Never `pip install`
anything yourself.

`carbon_start.sh` returns immediately - it launches the monitor in the
background and prints a one-screen summary. If a command appears to hang, you
ran the CLI instead of the script.

Omitting `label` on `carbon_end` / `carbon_report` uses the most recently
started run. Each run gets its own directory under `runs/<label>/` in this
skill's directory:

| file | what it is |
|---|---|
| `.codecarbon.config` | output paths + sampling interval for this run |
| `monitor.pid` | pid of the background monitor; absent when not running |
| `watchdog.pid` | pid of the lifecycle watchdog (see below) |
| `harness.pid` / `.start` / `.comm` | the session this run is tied to |
| `stopped_by` | why the run ended, if it was not `carbon_end` |
| `started_at` / `ended_at` | the run's wall-clock window; `ended_at` appears at stop |
| `session.json` | the starting session's transcript, for token accounting; absent if it could not be identified |
| `emissions.csv` | codecarbon's output, **written at stop**; rows are cumulative |
| `monitor.log` | monitor stderr — check here if `carbon_start` fails |
| `grid` | the country/region used for CO2e and how it was chosen |
| `power_mode` | the CPU and GPU methods codecarbon chose, e.g. `cpu: RAPL (measured); gpu: pynvml (measured)` |

## How it works

- `carbon_start` writes the run config, then launches the monitor detached in
  its own session (`setsid` on Linux, `os.setsid()` via the skill's python on
  macOS) with the run dir as cwd, and saves its pid. Before that it fixes the
  electricity grid for the run (see "Grid" below); the monitor itself then runs
  offline with that grid and sends nothing to codecarbon.io. It refuses to start a second monitor for a live label.
- `carbon_end` kills the watchdog first, then sends the monitor **SIGTERM**; codecarbon installs its own handler that calls
  `tracker.stop()` and flushes the final row. It waits up to 40 s, and only then
  escalates to SIGKILL (which loses the final row).
- `carbon_report` reads `emissions.csv` only — no live process needed. Rows are
  cumulative from tracker start, so it reports the **last row of the last
  `run_id`**. While a monitor is live there is no CSV yet, so it falls back to
  parsing the running totals out of `monitor.log` and says `[LIVE]`; CO2e is
  computed by codecarbon only at stop, so a live report shows energy, not
  emissions.

Env overrides: `CARBON_RUN_ROOT`, `CARBON_COUNTRY` / `CARBON_REGION` (grid
for this machine's electricity; default: detected), `CARBON_MEASURE_SECS`
(default `10`).

**Grid.** CO2e is energy times the grid's carbon intensity, so the country
matters as much as the measurement. `scripts/locate.py` resolves it once per
run, the way codecarbon's online mode does: the public IP is looked up at
get.geojs.io, then ipinfo.io (the only network requests the skill makes; none
if `CARBON_COUNTRY` is set). Unlike codecarbon, which gives each 0.5 s and
then silently assumes Canada/Quebec (a near-zero-carbon grid), a failed lookup
falls back to the last location detected on this machine, then to `NLD`, and
says so: `carbon_start` prints the `Grid:` line and the run dir records it in
`grid`. If that line says `LOOKUP FAILED`, tell the user their CO2e may be for
the wrong country and how to set `CARBON_COUNTRY`. On a VPN the detected
country is the VPN's.

## Reporting rule - relay, do not narrate

`carbon_report` and `carbon_end` print a complete, finished report. **Show it to
the user verbatim, in a code block, and stop there.** Do not summarise it, do not
rebuild it as a table of your own, do not recompute or convert any figure, and
do not add explanations the tool did not print - anything on top is unverified.

The report has three blocks - CodeCarbon (this machine, measured), Tokens (this
session, billed) and Provider inference (the provider's datacenter, estimated). They answer
different questions and **must not be added together**; the report says so
itself at the foot. Do not present the EcoLogits figures as a measurement of
the provider's infrastructure, and do not present a combined "total footprint".

The report deliberately prints **no Assumptions block**, so it no longer
discloses the caveats itself: whole-machine tracking, GPU idle draw, the grid
intensity used, and whether CPU power was measured from a hardware counter or
merely estimated. They still apply to every figure in it. `carbon_start` states
the CPU power mode when tracking begins, `power_mode` in the run dir records it,
and "Read the report honestly" below explains them - mention the ones that bear
on what the user asked, and never present a TDP estimate as a measurement.

The measurement attributes nothing to any particular program, so never explain a
figure by guessing at a cause ("likely the GPU training job") - that is invention,
not data. If you have no tool output to relay, say so. Never describe a run you did not
start, and never report numbers that did not come from these commands.

## Lifecycle - a run never outlives its session

Tracking must never be left running by accident, so a run is bound to the
session that started it and is stopped two independent ways.

1. **Watchdog.** `carbon_start` walks its own ancestry past the shells to the
   first real process - the harness, e.g. `claude` - and records its pid *and*
   its start time (from `/proc` on Linux, `ps -o lstart` on macOS), so a
   recycled pid cannot masquerade as it. A
   detached watchdog polls every 5 s and, the moment that process is gone,
   SIGTERMs the monitor so codecarbon still flushes its final row. Stops within
   ~2 s of the session dying, including a SIGKILLed terminal.
2. **Orphan sweep.** If the watchdog is killed too (the whole session tree gets
   SIGKILLed), every `carbon_start` / `carbon_report` / `carbon_end` call first
   scans all run dirs and stops any monitor whose recorded harness is gone. So
   the next carbon command of any kind cleans up the last session's leftovers.

Either path writes the reason into `stopped_by`, and `carbon_report` prints it,
so a run that ended by watchdog rather than by `carbon_end` is never mistaken
for a clean stop. Runs belonging to *live* sessions are never touched, so two
concurrent sessions do not interfere.

Override the binding with `CARBON_PARENT_PID=<pid>` (pin to some other process)
and the poll interval with `CARBON_WATCHDOG_POLL`. To check for leftovers by
hand: `ps ax | grep "[c]odecarbon-real monitor"`.

## Token accounting

Every report ends with a **Tokens** section: API calls, tokens sent (split into
fresh / cache read / cache write), tokens received, `Cache hit %` and
`Average context`, plus a per-model table when more than one model was used. It
is there to answer "is context staying clean and are we being efficient" - a
rising `Average context` or a falling `Cache hit %` is the signal that context
is bloating.

These are the only token figures the report prints. **Do not compute others
from them** - no peak context, no per-call output, no cost estimate. If the user
wants one, add it to `render()` in `tokens.py` so it is measured rather than
guessed at in the reply.

**Scope is one session: the one that ran `carbon_start`**, bound the same way
the watchdog binds the monitor's lifetime to it. Concurrent sessions - another
terminal, another harness - are not counted. Subagent calls *are*, because they
are the session's own tokens. Note this differs from the energy figures above
it, which are unavoidably whole-machine; the report states that itself.

These are **not tokenizer estimates**. Do not reach for tiktoken: it is
OpenAI's BPE and would be both wrong for Claude models and blind to the system
prompt, tool schemas and cache structure that dominate real usage. Instead
`scripts/tokens.py` reads the `usage` object the harness already writes to its
own session log, i.e. the counts the provider actually billed:

| harness | transcript | usage fields |
|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/<session-uuid>.jsonl` (or under `$CLAUDE_CONFIG_DIR`) | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` |
| pi | `~/.pi/agent/sessions/<slug>/<stamp>_<uuid>.jsonl` | `input`, `cacheRead`, `cacheWrite`, `output`, `reasoning` |

Claude Code re-serialises an assistant message on every stream update, so rows
are deduplicated on `message.id` - counting lines instead would inflate the
total several-fold.

### How the session is identified

Resolved **once, by `carbon_start`**, which runs as a child of the harness and
so still has its environment; the result is written to
`session.json` and every later report just reads that file. Three tiers, in
order, with the one used printed by `carbon_start`:

1. **The harness's session-id env var** (`$CLAUDE_CODE_SESSION_ID`) resolved
   against its transcript root. Exact; this is the normal path.
2. **A `.jsonl` the harness process holds open**, found via `/proc/<pid>/fd`,
   for harnesses that keep a write handle open. Linux only; skipped on macOS.
3. **Newest transcript in the session dir matching the harness cwd.** A guess -
   it picks the wrong session if two share a cwd - so it is labelled
   `INFERRED` in both `carbon_start`'s output and the report itself. pi exports
   no session id, so pi lands here unless it holds its log open.

If all three fail, **no tokens are reported**. There is deliberately no
machine-wide fallback: a number that silently included other sessions would be
worse than no number. Pin it by hand with
`CARBON_SESSION_TRANSCRIPT=/path/to/session.jsonl` (plus
`CARBON_SESSION_HARNESS=claude-code|pi` if it is not Claude Code) before
`carbon_start`.

To add a harness, add an entry to `HARNESSES` in `tokens.py`: a reader, its
transcript root, the env var holding its session id, and a glob to find that
id's file. Check resolution without starting a run:

```sh
python scripts/tokens.py --resolve <harness-pid> <cwd>     # prints session.json
python scripts/tokens.py <started_at> [<ended_at>|-] [<session-json>]
python scripts/provider_impacts.py <rundir>                # the EcoLogits block
python scripts/provider_impacts.py --json <rundir>         # every request's estimate
```

A harness added to `HARNESSES` gets the EcoLogits block for free, provided its
`Call.model` carries something `provider_impacts.split_model()` can read: a
`provider/model` pair, a router-qualified one (`openrouter/anthropic/...`), a
Bedrock/Vertex id, a bare `claude-*` name, or any bare name only one provider in
the EcoLogits registry claims. Add a spelling to `PROVIDERS` if a harness uses
one that is not there; nothing else needs to change.

**Never divide tokens into the energy or emissions figures.** Inference ran in
a provider datacenter; the Wh measured here is this machine's own draw, and the
two do not even cover the same scope - one session's tokens against the whole
machine's power. A "Wh per 1k tokens" built from them is meaningless. The report
no longer prints this caveat, so it is on you to honour it. The question it
tries to answer - what did the inference itself cost - is answered instead by
the EcoLogits block below, which models it rather than dividing one unrelated
number by another.

## Provider-side inference - the EcoLogits estimate

The last block of the report estimates what the session's *inference* cost, in
the provider's datacenter, with [EcoLogits](https://ecologits.ai). It reports
energy, CO2e, water, primary energy and ADPe, each as a **range**, plus a
per-model breakdown. `scripts/provider_impacts.py` owns it, kept apart from the
CodeCarbon path so a change to one can never move the other.

**The block is provider-neutral prose over per-model data.** It never names a
vendor in its headings or caveats; the provider, the model actually computed
with and the grid it was charged to appear in the `By model` table and the
`Grid zone` line, per model, because those are the only parts that are not
general. Keep it that way when editing - EcoLogits covers OpenAI, Mistral,
Cohere, Google and Hugging Face too, and `split_model()` already reads
`openai/gpt-4o`, `openrouter/anthropic/claude-sonnet-4-5`, Bedrock ids and bare
names, so the same block serves them unchanged.

**Nothing in that block is a measurement.** It is EcoLogits'
[LLM inference model](https://ecologits.ai/latest/methodology/llm_inference/)
applied to counts this skill read from the transcript. Report it as an estimate,
with its range, and never add it to the CodeCarbon energy.

Five properties of the method decide how it must be read. Say the ones that
bear on the question; never quote the mean alone as if it were a reading.

1. **Only output tokens and latency enter the model.** Input, cache-read and
   cache-write tokens do not appear in its formulas at all. So the block prices
   the *generation*, not the session - and for a coding agent, whose prompts
   dwarf its replies, that is a much smaller thing than "the footprint of my
   Claude usage". The report labels the line `Priced on N output tokens` for
   exactly this reason.
2. **It is computed per request, never on session totals.** The model is
   non-linear in output length and Claude Code sessions are wildly
   heterogeneous - 183 separate calculations summed is a different, and
   correct, number compared to one calculation over 185k tokens. Per-request
   results are retained; `python scripts/provider_impacts.py --json <rundir>`
   dumps every one of them with the model, resolution, tokens and latency used.
3. **The ranges are real uncertainty, not rounding.** When a provider does not
   publish its architecture - the usual case, and Anthropic's - EcoLogits
   carries a parameter-count *interval* and every impact comes out as one.
   Ranges are summed bound-wise, which assumes the whole session sits at one
   end: deliberately conservative, and wider than reality. EcoLogits itself
   says impacts for Anthropic are estimated "with a very low precision". A
   provider that does publish gets a scalar, and the block prints it as one.
4. **The model is often a stand-in.** A harness generally runs models newer
   than the EcoLogits release knows - `claude-opus-5` today - so `resolve()`
   falls back to the nearest registered model of the same family
   (`claude-opus-4-8`), for any provider. The
   `By model` table names the substitution on every line it affects. A model
   with no family match at all is listed as `NOT MODELLED` and its tokens are
   excluded from the totals and reported as excluded, rather than silently
   dropped. **Mention the substitution whenever you quote these numbers.**
5. **Latency is an upper bound, not a driver.** EcoLogits uses
   `min(measured latency, modelled generation time)`, so latency can only ever
   lower the estimate. `tokens.py` derives it from the transcript: the gap from
   the record that triggered the request (the user turn, or the tool_result the
   model was waiting on) to the last line of the response. That is an
   approximation - Claude Code records no latency field - but erring long is
   harmless by construction.

Grid: each provider's inference is charged to *its* datacenter location, with
its PUE and WUE, as EcoLogits records them - USA for Anthropic, SWE for Mistral,
and so on. It is **not** charged to `CARBON_COUNTRY`, which applies only to this
machine. A session that used two providers is charged to two grids and the
`Grid zone` line names both. Override with `CARBON_ECOLOGITS_ZONE=<ISO3>` if you
know the session was served elsewhere.

If the `ecologits` package is missing the block says so and the rest of the
report is unaffected; an EcoLogits failure can never take the token counts down
with it.

### What it is for

Making the workload observable, not producing a score. One Claude Code request
fans out into reads, tool calls, retries and subagents, so the unit of AI
consumption is a *workload*, not a message - and none of it is visible from the
terminal. With a per-request estimate you can measure a change instead of
arguing about it: does pruning context help, does a smaller model for a subtask
matter, does this new skill cause more inference. Measure the same task twice
and compare. Note what point 1 above implies for that loop: cache and context
work will move the **Tokens** block, and barely move the EcoLogits block.

## Read the report honestly

Two caveats the scripts print for themselves; repeat them when reporting numbers
to the user rather than quoting the totals bare.

1. **It measures the whole machine.** codecarbon's default `tracking_mode` is
   `machine` and `monitor` has no process filter, so browser, editor and this
   Claude session are in the total. For an attributable number, run an idle
   baseline of similar length and subtract:
   ```sh
   carbon_start idle    # wait ~60s, touch nothing
   carbon_end   idle
   carbon_start demo    # run the workload
   carbon_end   demo
   ```
2. **CPU power is measured only where codecarbon can read a hardware
   counter.** codecarbon picks its CPU method at start-up; `carbon_start` prints
   it (`CPU: RAPL (measured)` or `CPU: cpu_load - ESTIMATE, not measured`) and
   `power_mode` in the run dir records it. The report itself does not show it,
   so say it yourself whenever the CPU figure is an estimate. Measured methods
   are `RAPL`, `PowerMetrics`, `Power Gadget` and `Windows EMI`; `cpu_load`
   (utilisation times a table wattage), `TDP constant` and `global constant` are
   estimates - codecarbon's own validation puts them at roughly -60% to +190%
   of RAPL.

   - **Linux:** RAPL counters exist on most Intel and AMD CPUs but are
     root-only by default (CVE-2020-8694, the PLATYPUS side channel), so
     codecarbon falls back to an estimate. `carbon_start` then prints
     codecarbon's own fix from
     https://docs.codecarbon.io/latest/how-to/enable-rapl/ - a `chmod` that
     lasts until reboot, or a `codecarbon` group plus a udev rule that makes
     it permanent for that user only. **Never run these yourself**: they need
     the user's sudo and change the machine's security posture. Show the
     user the commands `carbon_start` printed and let them decide. In VMs and
     containers there is usually no RAPL at all; nothing can be enabled.
   - **macOS:** codecarbon uses `cpu_load` and does not use sudo. Per its docs
     there is no known way to read Apple Silicon energy without administrative
     rights, so there is nothing to enable. CPU figures on a Mac are always
     estimates; the Apple GPU is not tracked separately.

An NVIDIA GPU (NVML) or AMD GPU (amdsmi) is genuinely measured, but an idle
discrete GPU still draws tens of watts, so a CPU-bound workload accrues GPU
energy that is not its own. The report no longer flags this, so note it
yourself whenever GPU energy is non-zero.

## Platform support

| | Linux | macOS | Windows |
|---|---|---|---|
| tracking, watchdog, reports | yes | yes | only inside WSL |
| CPU power | RAPL (measured) if readable, else estimate | estimate (`cpu_load`) | - |
| GPU power | NVIDIA / AMD, measured | not tracked | - |
| session tokens | yes | yes | - |

The scripts are bash 3.2 compatible (macOS's bash) and branch on `uname -s`
for every process lookup.

## Layout and requirements

Installed in the shared skills directory, so every harness that reads it
(Claude Code, pi, ...) picks it up:

```
~/.claude/skills/carbon/
  SKILL.md
  pyproject.toml, uv.lock   the skill's own Python environment, pinned
  scripts/     carbon_start.sh  carbon_end.sh  carbon_report.sh
               common.sh  watchdog.sh  report.py  report_live.py
               sections.py         the two usage blocks, built from one
                                   transcript read and shared by both reports
               tokens.py           billed usage - measured
               provider_impacts.py EcoLogits estimate - modelled,
                                   provider-agnostic
  .venv/       created by the installer: codecarbon (CLI guarded), ecologits
  runs/        one directory per run
```

Self-contained and path-independent: the scripts resolve the vendored CLI and
python relative to their own location, so they need no PATH entry, no conda,
and never touch any project's environment. `carbon_start` / `carbon_end` /
`carbon_report` in `~/.local/bin/` are one-line wrappers onto `scripts/`.

## Installation

Requires Linux or macOS, and [uv](https://docs.astral.sh/uv/). From a clone
of the repository that ships this skill:

```sh
bash carbon_skill/install.sh            # install, or update in place
bash carbon_skill/install.sh --uninstall
```

The installer copies the skill here, runs `uv sync --frozen` to build `.venv/`
from `uv.lock` (uv fetches Python 3.12 itself if needed), moves the real
codecarbon CLI to `.venv/bin/codecarbon-real` behind a refusing shim, writes the
three wrappers, and runs a 15-second test measurement. It never uses sudo. To
repair a broken install, run it again. Details: `carbon_skill/README.md`.
