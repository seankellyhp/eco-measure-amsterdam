# Methodology: the EcoLogits estimate, and reading the report honestly

## Provider-side inference - the EcoLogits estimate

The last block of the report estimates what the session's *inference* cost, in
the provider's datacenter, with [EcoLogits](https://ecologits.ai). It reports
energy, CO2e, water, primary energy and ADPe, each as a **range**, plus a
per-model breakdown. `provider_impacts.py` owns it, kept apart from the
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
   results are retained; `python -m carbon_skill.provider_impacts --json <label|@id>` (with the program's Python)
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
   carbon start idle    # wait ~60s, touch nothing
   carbon end   idle
   carbon start demo    # run the workload
   carbon end   demo
   carbon compare --baseline idle demo
   ```
2. **CPU power is measured only where codecarbon can read a hardware
   counter.** codecarbon picks its CPU method at start-up; `carbon start` prints
   it (`CPU: RAPL (measured)` or `CPU: cpu_load - ESTIMATE, not measured`) and
   `cpu_method` on the run's row in the database records it. The report itself does not show it,
   so say it yourself whenever the CPU figure is an estimate. Measured methods
   are `RAPL`, `PowerMetrics`, `Power Gadget` and `Windows EMI`; `cpu_load`
   (utilisation times a table wattage), `TDP constant` and `global constant` are
   estimates - codecarbon's own validation puts them at roughly -60% to +190%
   of RAPL.

   - **Linux:** RAPL counters exist on most Intel and AMD CPUs but are
     root-only by default (CVE-2020-8694, the PLATYPUS side channel), so
     codecarbon falls back to an estimate. `carbon start` then prints
     codecarbon's own fix from
     https://docs.codecarbon.io/latest/how-to/enable-rapl/ - a `chmod` that
     lasts until reboot, or a `codecarbon` group plus a udev rule that makes
     it permanent for that user only. **Never run these yourself**: they need
     the user's sudo and change the machine's security posture. Show the
     user the commands `carbon start` printed and let them decide. In VMs and
     containers there is usually no RAPL at all; nothing can be enabled.
   - **macOS:** codecarbon uses `cpu_load` and does not use sudo. Per its docs
     there is no known way to read Apple Silicon energy without administrative
     rights, so there is nothing to enable. CPU figures on a Mac are always
     estimates; the Apple GPU is not tracked separately.
   - **Windows:** codecarbon reads CPU energy through the Energy Meter
     Interface (Windows 11 on bare metal, not a VM) or Intel Power Gadget if
     installed (`Windows EMI` / `Power Gadget`, both measured). Otherwise it
     estimates from CPU load.

An NVIDIA GPU (NVML) or AMD GPU (amdsmi) is genuinely measured, but an idle
discrete GPU still draws tens of watts, so a CPU-bound workload accrues GPU
energy that is not its own. The report no longer flags this, so note it
yourself whenever GPU energy is non-zero.

