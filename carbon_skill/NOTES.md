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

- **Step 0 spike (Windows detach)**: skipped at the user's request. `CREATE_BREAKAWAY_FROM_JOB` is not used; if the manual checklist on Windows shows the monitor dying with the tool call, add it in `procs.spawn_detached` (with a retry without it on `PermissionError`).
- **Codex transcript reader (5.12)**: not written. Codex is not installed on this machine and no sample session file was available; the plan forbids writing the reader from the description alone. A Codex session gets energy figures but no Tokens/Provider blocks. Needed: one real `~/.codex/sessions/**/rollout-*.jsonl`.
- **macOS and Windows**: not run. Only the CI workflow covers them, and it has not been pushed.
- **Manual checklist (8)**: not run in any agent.
- **`uv tool install ./carbon_skill` (route A)**: not run on this machine, because the old bash wrappers in `~/.local/bin` would collide (see README); covered by CI.
- **Tests**: kept minimal at the user's request (labels, token dedup, `split_model`, sweep, install-skill, one slow start/report/end lifecycle test). The rest of section 7 is not written.
