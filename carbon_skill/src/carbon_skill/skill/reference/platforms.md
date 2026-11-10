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
tracker and saves a cumulative sample to the database every interval. The run
is bound to the agent process that started it (pid and creation time, so a
recycled pid is not mistaken for it). It stops when:

- `carbon end` is run (it writes a `stop` file and waits up to 40 s);
- the agent process exits (checked every second);
- the monitor receives a termination signal.

If the monitor itself was killed, the next `carbon` command marks the run
`stopped` with `stopped_by: monitor died`; figures are those of the last flush.
Runs bound to a live agent are never touched. A report prints
`(stopped by: ...)` for any run not ended by `carbon end`.

## Data model

Everything is in one SQLite database, `carbon.db`, in the data folder:
`CARBON_RUN_ROOT`, else `~/.local/share/carbon-skill/runs` on Linux,
`~/Library/Application Support/carbon-skill/runs` on macOS,
`%LOCALAPPDATA%\carbon-skill\carbon-skill\runs` on Windows. Uninstalling the
skill does not delete it. Do not point `CARBON_RUN_ROOT` at a synced or network
folder (OneDrive, Dropbox, NFS): SQLite's write-ahead log is not safe there.

```
session 1 ---- n run 1 ---- n sample             CodeCarbon, measured
                     1 ---- n api_call 1 ---- 0..1 provider_estimate
                              tokens, exact          EcoLogits, estimated
```

| table | one row per | holds |
|---|---|---|
| `session` | agent session | harness, its session id, transcript path, how it was identified |
| `run` | `carbon start` | label, state, start/end, `stopped_by`, monitor and agent process, grid, CPU/GPU method, hardware, versions, when usage was saved |
| `sample` | flush | cumulative duration, energy (`_kwh`), power (`_w`), emissions (`_kg`), water; the last row is the run's total |
| `api_call` | billed request in the run's window | model, fresh / cache-read / cache-write / output / thinking tokens, subagent flag, latency |
| `provider_estimate` | request EcoLogits looked at | model computed with and how matched; low and high bounds of energy (kWh), GWP (kg CO2e), ADPe (kg Sb eq), PE (MJ), water (L) |

Views: `run_total` (each run's last sample), `run_tokens` (each run's token
totals). Tokens and estimates are saved when a run stops, so its report no
longer needs the transcript; while a run is live they are read from the
transcript. The machine and provider tables are never joined into one figure.

Query it with any SQLite client, or export: `carbon export @<id>` writes one
run's samples with CodeCarbon's `emissions.csv` columns, `carbon export
--format sql` the whole database as SQL text (also the backup).

Each run also has a folder named after its id, holding `monitor.log`
(CodeCarbon's log; check it if `carbon start` fails) and, briefly, the `stop`
file `carbon end` uses to stop the monitor. Run folders from before the
database are imported on first use and moved to `imported/`.

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
