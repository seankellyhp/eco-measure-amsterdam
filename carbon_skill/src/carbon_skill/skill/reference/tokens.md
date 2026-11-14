# Token accounting

Every report has a **Tokens** block: API calls, tokens sent, tokens received,
`Cache hit %` and `Average context`, plus a per-model table when more than one
model was used. A rising `Average context` or a falling `Cache hit %` is the
signal that context is bloating.

These are the only token figures the report prints. **Do not compute others
from them** - no peak context, no per-call output, no cost estimate. If one is
needed, add it to `render()` in `tokens.py` so it is measured, not guessed.

## Where the counts come from

Not a tokenizer. `tokens.py` reads the `usage` object each harness writes to its
own session log - the counts the provider actually billed. Never reach for
tiktoken: it is OpenAI's BPE, wrong for Claude, and blind to the system prompt,
tool schemas and cache structure that dominate real usage.

| harness | transcript | usage fields |
|---|---|---|
| Claude Code | `~/.claude/projects/<slug>/<session-uuid>.jsonl` (or under `$CLAUDE_CONFIG_DIR`) | `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` |
| pi | `~/.pi/agent/sessions/<slug>/<stamp>_<uuid>.jsonl` | `input`, `cacheRead`, `cacheWrite`, `output`, `reasoning` |
| Codex | `~/.codex/sessions/<year>/<month>/<day>/rollout-...<session-uuid>.jsonl` (or under `$CODEX_HOME`) | `token_usage_record.payload.usage`: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens` |

Claude Code writes one line per content block of an assistant message, each
with the same `message.id` and the same final usage, so rows are deduplicated
on `message.id`. Subagent (`isSidechain`) rows are in the same file and are
counted - they are the session's tokens too.

Codex writes one `token_usage_record` per response. Those records contain the
response's usage as well as cumulative thread totals; only the per-response
`usage` object is counted, with repeated `response_id` values deduplicated.
Codex's `input_tokens` includes cached input, so cached and cache-write counts
are subtracted before the fresh-input total is calculated. Reasoning tokens
are already included in `output_tokens`.

## Scope: one session

The session that ran `carbon start`. Concurrent sessions are not counted. The
energy figures, by contrast, are whole-machine.

## How the session is identified

Resolved once by `carbon start` (it runs inside the agent's environment) and
stored with the run (the `session` table). Three tiers, in order; the one
used is printed by `carbon start`:

1. **The harness's session-id variable** (`$CLAUDE_CODE_SESSION_ID`,
   `$PI_SESSION_ID` or `$CODEX_SESSION_ID`), resolved against its transcript
   root. Exact; the normal path.
2. **A `.jsonl` the agent process holds open**, via `/proc/<pid>/fd`. Linux only.
3. **Newest transcript in the session folder matching the cwd.** A guess - wrong
   if two sessions share a cwd - so it is labelled `INFERRED` in `carbon start`
   and in the report.

If all fail, no tokens are reported; there is deliberately no machine-wide
fallback. Pin it by hand before `carbon start`:
`CARBON_SESSION_TRANSCRIPT=/path/to/session.jsonl` (plus
`CARBON_SESSION_HARNESS=claude-code|pi|codex`).

## Adding a harness

Add an entry to `HARNESSES` in `tokens.py`: a reader, its transcript root, the
variable holding its session id, and a glob to find that id's file. The
EcoLogits block follows for free if `Call.model` is something
`provider_impacts.split_model()` can read (`provider/model`, a router-qualified
name, a Bedrock id, a bare `claude-*` name, or a bare name only one provider
claims). Add a spelling to `PROVIDERS` if needed.
