# Platforms, lifecycle and configuration

## Per-OS support

| | Linux | macOS | Windows |
|---|---|---|---|
| tracking, auto-stop, reports | yes | yes | yes (native) |
| CPU power | RAPL, measured, if readable; else estimate | estimate (`cpu_load`) | Windows EMI (Win 11, bare metal) or Power Gadget, measured; else estimate |
| GPU power | NVIDIA / AMD, measured | not tracked separately | NVIDIA / AMD, measured |
| session tokens | Claude Code, pi | Claude Code, pi | Claude Code, pi |

Session identification tier 2 (open file handles) is Linux-only; the others
work everywhere.

## Grid

CO2e is energy times the grid's carbon intensity. The grid is resolved once
per run by `carbon start`: `CARBON_COUNTRY` if set (no network request), else
the public IP is looked up at get.geojs.io, then ipinfo.io. If both fail it
uses the last location detected on this machine, then `NLD`, and says so in the
`Grid:` line. If that line says `LOOKUP FAILED`, tell the user their CO2e may be
for the wrong country and how to set `CARBON_COUNTRY`. On a VPN the detected
country is the VPN's. The monitor itself runs offline.

## Lifecycle

`carbon start` launches a detached monitor process that owns one codecarbon
tracker and writes a cumulative row to `emissions.csv` every interval. The run
is bound to the agent process that started it (pid and creation time, so a
recycled pid is not mistaken for it). It stops when:

- `carbon end` is run (it writes a `stop` file and waits up to 40 s);
- the agent process exits (checked every second);
- the monitor receives a termination signal.

If the monitor itself was killed, the next `carbon` command marks the run
`stopped` with `stopped_by: monitor died`; figures are those of the last flush.
Runs bound to a live agent are never touched. A report prints
`(stopped by: ...)` for any run not ended by `carbon end`.

## Run folder

Runs live under `CARBON_RUN_ROOT`, else the user data folder
(`~/.local/share/carbon-skill/runs` on Linux,
`~/Library/Application Support/carbon-skill/runs` on macOS,
`%LOCALAPPDATA%\carbon-skill\carbon-skill\runs` on Windows), one folder per label.
Uninstalling the skill does not delete them.

| file | content |
|---|---|
| `run.json` | label, interval, grid, agent (pid, name, how detected), cwd, version |
| `session.json` | the transcript used for tokens; absent if not identified |
| `status.json` | state, monitor pid, started/ended, stopped_by, CPU and GPU method, last flush |
| `emissions.csv` | codecarbon's output; one cumulative row per flush |
| `monitor.log` | codecarbon's log; check it if `carbon start` fails |

## Environment variables

| variable | effect |
|---|---|
| `CARBON_RUN_ROOT` | where runs are stored |
| `CARBON_COUNTRY`, `CARBON_REGION` | grid for this machine (ISO-3; region for USA, CAN, ...) |
| `CARBON_MEASURE_SECS` | sampling and flush interval, default 10 |
| `CARBON_GEO_TIMEOUT` | seconds per location lookup, default 4 |
| `CARBON_PARENT_PID` | bind the run to this process instead of the detected agent |
| `CARBON_SESSION_TRANSCRIPT`, `CARBON_SESSION_HARNESS` | pin the token session by hand |
| `CARBON_ECOLOGITS_ZONE` | charge provider inference to this grid zone |
