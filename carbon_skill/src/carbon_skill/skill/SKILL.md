---
name: carbon
description: Track the energy use, CO2e emissions and LLM token usage of work done on this machine with CodeCarbon, estimate the provider-side impact of the inference the session paid for with EcoLogits, and compare runs to reduce the footprint. Use when the user asks to start/stop energy tracking, measure the power or carbon cost of a run, demo or benchmark, or wants a report of compute time, energy, CPU/GPU/RAM breakdown, estimated emissions, water use, how many tokens were sent and received (context size, cache hit rate, prompt efficiency), what the API calls themselves cost the environment, or how to reduce it. Triggers include "carbon_start", "carbon_end", "carbon_report", "carbon compare", "track energy", "how much power did that use", "emissions of this run", "how many tokens did that use", "is my context clean", "ecologits", "footprint of my Claude usage", "reduce my footprint".
---

# carbon

Two scopes, measured and reported separately, never summed:

```
              AGENT SESSION
                    |
        .-----------+-----------.
        |                       |
   THIS MACHINE              PROVIDER
   CodeCarbon                EcoLogits
   MEASURED                  ESTIMATED
   whole-machine draw        inference for this
   while the run was live    session's output tokens
```

## Commands

```sh
{{CARBON_CMD}} start  [label]        # begin tracking; returns in a few seconds
{{CARBON_CMD}} end    [label]        # stop, then print the report
{{CARBON_CMD}} report [label]        # report for a past or live run
{{CARBON_CMD}} compare A B           # B against A, with deltas
{{CARBON_CMD}} compare --baseline IDLE TASK   # TASK minus idle run, scaled
{{CARBON_CMD}} list                  # runs, newest first
{{CARBON_CMD}} doctor                # check the installation
```

Labels default to `default` for `start` and to the last started run otherwise.
A run stops by itself when this agent session exits.

**Never run the `codecarbon` CLI directly**, and never `pip install` anything:
these commands are the whole interface. If one fails, show the error and
suggest `{{CARBON_CMD}} doctor`.

## Rules for reporting

- **Relay verbatim.** Show the output of `end`, `report` and `compare` in a
  code block and stop. Do not summarise, reformat, recompute or explain causes.
- **Never sum the scopes.** CodeCarbon (this machine) and EcoLogits (provider)
  are different scopes and methods; never present a combined total.
- **Never divide tokens into the energy or emissions figures.** A "Wh per 1k
  tokens" from them is meaningless.
- **Whole machine.** CodeCarbon measures everything running, not one program.
  For an attributable figure, use an idle baseline: `start idle`, wait about a
  minute touching nothing, `end idle`, then `compare --baseline idle <task>`.
- **Measured versus estimated CPU.** `start` prints `CPU: <method> (measured)`
  or `- ESTIMATE, not measured`. Say so when the CPU figure is an estimate. If
  it prints sudo commands to enable RAPL, show them to the user; **never run
  sudo yourself**.

## Reducing the footprint

When asked how to lower it, offer these as experiments, not causes: change one
thing, run the same task again under a new label, and let
`{{CARBON_CMD}} compare` judge.

| Signal in the report | Try |
|---|---|
| Low `Cache hit %` | keep the start of the prompt stable; avoid editing early context mid-session |
| Rising `Average context` | clear or compact between tasks; read narrower file ranges; fewer, smaller tool outputs |
| Large model in `By model` for routine work | a smaller model for searches and mechanical edits |
| Many subagent calls | do small tasks inline |
| High machine energy above idle | check for local jobs (tests, builds, indexing) left running |

Cache and context changes move the Tokens block much more than the EcoLogits
block, which prices output tokens only.

## Reference (open only when needed)

- `reference/methodology.md` - how the EcoLogits estimate works and how to read the report honestly; open when quoting provider figures or explaining a caveat.
- `reference/tokens.md` - token accounting and session identification; open when tokens are missing or look wrong.
- `reference/platforms.md` - per-OS support, grid detection, run lifecycle, run folder files, environment variables; open for setup or troubleshooting.
