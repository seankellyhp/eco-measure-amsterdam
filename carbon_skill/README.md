# `/carbon`: a Claude Code skill for measuring an agent's footprint

The workshop notebooks measure Python programs. This skill measures **the work
your AI agent does**. Ask Claude Code to "start carbon tracking", do some
work, then ask it to "stop carbon tracking", and you get a report with
three separate parts:

| Block | Scope | How |
|---|---|---|
| **CodeCarbon** | this computer (CPU, GPU, RAM), while tracking ran | measured with [CodeCarbon](https://codecarbon.io) |
| **Tokens** | the tokens this Claude Code session sent and received | exact counts from the session log, as billed |
| **Provider inference** | the energy, CO2e and water of generating those tokens in the provider's datacenter | estimated with [EcoLogits](https://ecologits.ai), as a range |

The three blocks answer different questions and are never added together.

It works on **Linux and macOS**. On Windows, use it inside
[WSL](https://learn.microsoft.com/windows/wsl/install).

---

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), the same
tool the workshop notebooks use:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # only if `uv --version` fails
```

Then, from the cloned workshop repository:

```bash
git clone https://github.com/seankellyhp/eco-measure-amsterdam   # if you have not already
cd eco-measure-amsterdam
bash carbon_skill/install.sh
```

It takes about a minute: it downloads codecarbon and ecologits (and Python 3.12
if you don't have it), then runs a 15-second test measurement. Afterwards,
start Claude Code (or restart it if it was already open) and type `/carbon`.

### Or let your agent install it

Open Claude Code in the `eco-measure-amsterdam` folder and paste:

> Install the carbon skill by following carbon_skill/README.md.

#### Instructions for the agent

If you are an AI agent asked to install this skill, do exactly this:

1. Check that `uv --version` works. If it does not, stop and ask the user to
   install uv (command above). Do not install it without asking.
2. From the repository root, run `bash carbon_skill/install.sh`. It takes
   about a minute; allow at least 5 minutes before timing out.
3. Show the user the installer's output, including the test measurement
   report, verbatim.
4. If the installer printed a `NOTE: CPU power is an ESTIMATE` block, tell the
   user, and show them the commands it printed. **Do not run any `sudo`
   command yourself.** Enabling CPU measurement is the user's decision (see
   "Measuring CPU power" below).
5. If the installer says the skill already exists and was not installed by
   it, stop and ask the user before re-running it with `--force`.
6. If it fails, show the error. Do not work around it by copying the folder by
   hand or by running `pip install`: the skill needs the environment the
   installer builds.
7. Tell the user to restart Claude Code if `/carbon` is not available yet.

---

## Use

In Claude Code, in plain language:

- "start carbon tracking" (or `/carbon start`)
- "how much energy so far?" (a live report)
- "stop carbon tracking and show me the report"

Or in a terminal:

```bash
carbon_start  [label]   # start tracking (default label: "default"); returns at once
carbon_end    [label]   # stop, then print the report
carbon_report [label]   # report for a past or running measurement
```

Each label is a separate measurement, so you can compare runs:

```bash
carbon_start idle      # touch nothing for ~60 s: the baseline
carbon_end   idle
carbon_start task      # now let the agent do the task
carbon_end   task
```

Tracking stops automatically when the Claude Code session that started it
ends, so a forgotten measurement never keeps running.

---

## Measuring CPU power

The first lines of `carbon_start` show whether the CPU is **measured** or
**estimated**:

```
CPU: RAPL (measured)
CPU: cpu_load - ESTIMATE, not measured
```

This is CodeCarbon's own choice. The skill shows what CodeCarbon decided and
does not change it.

**Linux.** Most Intel and AMD CPUs have energy counters (RAPL), but Linux only
lets root read them, as a fix for a security issue
([CVE-2020-8694](https://nvd.nist.gov/vuln/detail/CVE-2020-8694)). Without them
CodeCarbon estimates the CPU's power from its load. CodeCarbon's own tests put
that estimate at roughly 60% too low to 190% too high. When this happens,
`carbon_start` prints CodeCarbon's
[recommended fix](https://docs.codecarbon.io/latest/how-to/enable-rapl/). You
have two options:

- Until the next reboot (lets every user on the machine read the counters):

  ```bash
  sudo chmod a+r /sys/class/powercap/*/energy_uj
  ```

- Permanently, for your user only (CodeCarbon's recommended setup):

  ```bash
  sudo groupadd codecarbon
  sudo usermod -a -G codecarbon $USER
  printf '%s\n' 'SUBSYSTEM=="powercap", ACTION=="add", TEST=="energy_uj", RUN+="/bin/chgrp codecarbon /sys%p/energy_uj", RUN+="/bin/chmod 0440 /sys%p/energy_uj"' | sudo tee /etc/udev/rules.d/99-codecarbon-rapl.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --subsystem-match=powercap --action=add
  ```

  Then log out and back in, so your new group membership takes effect.

Both options need your password, so the skill never runs them for you. In a
virtual machine or container there are usually no counters at all, and the
CPU figure stays an estimate.

**macOS.** CodeCarbon estimates CPU power from the CPU's load, and does not
use `sudo`. According to CodeCarbon's documentation, there is no known way to
read Apple Silicon energy without admin rights, so there is nothing to enable.
On a Mac, CPU figures are always estimates and the GPU is not tracked
separately.

**GPU.** An NVIDIA or AMD GPU is measured. An idle GPU still draws power,
though, and that power counts towards the total.

---

## Settings

Set these before `carbon_start`, for example `CARBON_COUNTRY=DEU carbon_start`:

| Variable | Default | |
|---|---|---|
| `CARBON_COUNTRY` | detected | Country whose electricity grid sets this computer's CO2 per kWh, as an ISO-3 code (`NLD`, `DEU`, `GBR`, `USA`...). Set it to skip the location lookup. |
| `CARBON_REGION` | detected | Region within the country. CodeCarbon uses it for the USA, Canada, China and the Nordic countries (e.g. `california`). |
| `CARBON_MEASURE_SECS` | `10` | Seconds between power readings. |
| `CARBON_ECOLOGITS_ZONE` | provider's own | Grid zone for the provider-side estimate, if you know where it was served. |
| `CARBON_SESSION_TRANSCRIPT` | detected | Path to the session log to count tokens from, if detection fails. |

---

## Which electricity grid?

Emissions are energy times the CO2 per kWh of your electricity grid, so the
skill needs to know where you are. Like CodeCarbon, it looks up your public IP
address at [get.geojs.io](https://www.geojs.io), or
[ipinfo.io](https://ipinfo.io) if that fails, once each time tracking starts.
`carbon_start` shows the result:

```
Grid: NLD / north holland - Netherlands, north holland - detected from your IP address via get.geojs.io
```

If the lookup fails, CodeCarbon on its own would quietly assume Canada
(Quebec), whose grid is almost carbon-free. The skill uses the last location
it detected on your computer instead, or the Netherlands if it has never
detected one, and says so. On a VPN, the detected country is the VPN's. In
either case, set your country yourself:

```bash
CARBON_COUNTRY=DEU carbon_start
```

## What leaves your computer

Only the location lookup above, which sends your IP address to get.geojs.io
(or ipinfo.io), as CodeCarbon itself does. Setting `CARBON_COUNTRY` turns it
off. Measuring is offline, and nothing is sent to codecarbon.io. Token counts come from the session log that
Claude Code already keeps on your disk (`~/.claude/projects/`). The skill uses
only the usage numbers and timestamps in it, not what was said.

---

## Update and uninstall

```bash
git pull
bash carbon_skill/install.sh              # updates in place, keeps your past runs
bash carbon_skill/install.sh --uninstall  # removes the skill and its commands
```

Other options: `--dest DIR` (install somewhere other than
`~/.claude/skills/carbon`), `--bin-dir DIR` (put the commands somewhere other
than `~/.local/bin`), `--no-check` (skip the test measurement), and `--force`
(replace a carbon skill this installer did not create; the old one is moved
to a backup, not deleted). These are the defaults the installer uses:

| What | Where |
|---|---|
| the skill | `~/.claude/skills/carbon/` (respects `CLAUDE_CONFIG_DIR`) |
| its Python environment | `~/.claude/skills/carbon/.venv/` |
| your measurements | `~/.claude/skills/carbon/runs/<label>/` |
| the commands | `~/.local/bin/carbon_start`, `carbon_end`, `carbon_report` |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `uv is required but not on PATH` | Install uv (see above), open a new terminal, and run the installer again. |
| `carbon_start: command not found` | `~/.local/bin` is not on your PATH. The agent still works (it calls the scripts directly). To fix it for your terminal, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc` or `~/.bashrc`, or run `fish_add_path ~/.local/bin` in fish. |
| `/carbon` does not appear in Claude Code | Restart Claude Code. Skills are loaded when a session starts. |
| `The carbon skill is not installed` | The folder was copied by hand. Run `bash carbon_skill/install.sh`. |
| `REFUSED: do not run the codecarbon CLI directly` | This is intended: `codecarbon monitor` would block the agent. Use `carbon_start`. |
| `Tokens: session NOT identified` | Energy is still measured. To count tokens, set `CARBON_SESSION_TRANSCRIPT` to the session's `.jsonl` file before `carbon_start`. |
| Anything else | Look in `~/.claude/skills/carbon/runs/<label>/monitor.log`, then run the installer again. It is safe to re-run. |

---

## Files

```
carbon_skill/
  README.md       this file
  install.sh      the installer
  carbon/         the skill itself, copied to ~/.claude/skills/carbon
    SKILL.md        instructions Claude reads when the skill is used
    pyproject.toml  dependencies (codecarbon, ecologits) ...
    uv.lock         ... pinned to the versions the workshop notebooks use
    scripts/        carbon_start/end/report and the report code
```
