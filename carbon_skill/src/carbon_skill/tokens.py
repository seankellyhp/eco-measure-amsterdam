"""Exact token accounting for a carbon run, read from the starting session's transcript.

No tokenizer is involved and nothing is re-counted: every harness writes the
provider's own `usage` object to its session log, so these are the counts the
API actually billed.

Scope is **one session** - the session that ran `carbon_start`, the same one the
energy monitor's lifecycle is bound to. `carbon_start` resolves it once, while
it still has the harness's environment and live `/proc` entry, and records the
transcript path in the run dir; the report only reads that file. Other sessions
running concurrently are not counted, and if the session cannot be identified
the report says so rather than falling back to a machine-wide total.

  Claude Code   ~/.claude/projects/<slug>/<session-uuid>.jsonl
                assistant lines carry message.usage; the same message is
                re-serialised on every stream update, so rows are deduplicated
                on message.id. Subagent (isSidechain) rows live in this same
                file and are counted - they are the session's tokens too.
  pi            ~/.pi/agent/sessions/<slug>/<stamp>_<uuid>.jsonl
                type=message lines with message.usage (input / output /
                cacheRead / cacheWrite / reasoning).

Add a harness by giving it an entry in HARNESSES.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

HOME = Path.home()
# Claude Code keeps its data in $CLAUDE_CONFIG_DIR when set, ~/.claude otherwise.
CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude")


@dataclass
class Call:
    """One billed API request."""

    ts: datetime
    model: str
    fresh: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    thinking: int = 0
    sidechain: bool = False
    latency: float | None = None

    @property
    def context(self) -> int:
        """Prompt size actually sent, cached or not."""
        return self.fresh + self.cache_read + self.cache_write


@dataclass
class Totals:
    calls: list[Call] = field(default_factory=list)


def _parse_ts(value) -> datetime | None:
    if isinstance(value, (int, float)):
        # pi writes epoch millis alongside the ISO field.
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iter_lines(path: str):
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


# --------------------------------------------------------------------------- #
# readers - one per harness transcript format
# --------------------------------------------------------------------------- #


def read_claude_code(path: str, start: datetime, end: datetime, totals: Totals) -> None:
    """Claude Code rows, deduplicated on message.id and timed from the chain.

    A completed assistant message is written once per content block - thinking,
    text, tool_use - each as its own line carrying the *same* `message.id` and
    the *same* final `usage`. Counting lines would multiply the session's tokens
    several-fold, so only the first line of each id contributes usage.

    Latency comes from the same structure. The first line's `parentUuid` is the
    record that triggered the request - the user's message, or the tool_result
    the model was waiting on - and its timestamp is therefore when the request
    went out. The span to the *last* line of the message is the request's
    wall-clock duration. It is an approximation (the transcript is written after
    the fact, and no field records latency directly), but EcoLogits only ever
    uses it as an upper bound, so erring long is harmless.
    """
    ts_by_uuid: dict[str, datetime] = {}
    call_by_mid: dict[str, Call] = {}
    sent_by_mid: dict[str, datetime] = {}
    for rec in _iter_lines(path):
        ts = _parse_ts(rec.get("timestamp"))
        uuid = rec.get("uuid")
        if uuid and ts is not None:
            ts_by_uuid[uuid] = ts

        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        mid = msg.get("id") or rec.get("requestId") or ""
        if ts is None or not (start <= ts <= end):
            continue

        prior = call_by_mid.get(mid)
        if prior is not None:
            sent = sent_by_mid.get(mid)
            if sent is not None:
                prior.latency = max(prior.latency or 0.0, (ts - sent).total_seconds())
            continue

        details = usage.get("output_tokens_details") or {}
        call = Call(
            ts=ts,
            model=msg.get("model") or "unknown",
            fresh=int(usage.get("input_tokens") or 0),
            cache_read=int(usage.get("cache_read_input_tokens") or 0),
            cache_write=int(usage.get("cache_creation_input_tokens") or 0),
            output=int(usage.get("output_tokens") or 0),
            thinking=int(details.get("thinking_tokens") or 0),
            sidechain=bool(rec.get("isSidechain")),
        )
        sent = ts_by_uuid.get(rec.get("parentUuid") or "")
        if sent is not None and ts > sent:
            call.latency = (ts - sent).total_seconds()
            sent_by_mid[mid] = sent
        call_by_mid[mid] = call
        totals.calls.append(call)


def read_pi(path: str, start: datetime, end: datetime, totals: Totals) -> None:
    seen: set[str] = set()
    for rec in _iter_lines(path):
        if rec.get("type") != "message":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        mid = rec.get("id") or msg.get("responseId") or ""
        if mid in seen:
            continue
        ts = _parse_ts(rec.get("timestamp")) or _parse_ts(msg.get("timestamp"))
        if ts is None or not (start <= ts <= end):
            continue
        seen.add(mid)
        provider = msg.get("provider") or ""
        model = msg.get("model") or "unknown"
        totals.calls.append(
            Call(
                ts=ts,
                model=f"{provider}/{model}" if provider else model,
                fresh=int(usage.get("input") or 0),
                cache_read=int(usage.get("cacheRead") or 0),
                cache_write=int(usage.get("cacheWrite") or 0),
                output=int(usage.get("output") or 0),
                thinking=int(usage.get("reasoning") or 0),
            )
        )


# --------------------------------------------------------------------------- #
# session resolution - runs once, at carbon_start
# --------------------------------------------------------------------------- #

# name -> (reader, sessions root, env var holding the session id, glob for that id)
HARNESSES = {
    "claude-code": {
        "reader": read_claude_code,
        "root": CLAUDE_DIR / "projects",
        "id_env": ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID"),
        "by_id": "*/{id}.jsonl",
    },
    "pi": {
        "reader": read_pi,
        "root": HOME / ".pi/agent/sessions",
        "id_env": ("PI_SESSION_ID",),
        # pi names files <stamp>_<uuid>.jsonl, so match on the uuid suffix.
        "by_id": "*/*{id}.jsonl",
    },
}


def _newest_open_transcript(pid: str) -> tuple[str, str] | None:
    """(harness, path) for a .jsonl the harness process currently holds open."""
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return None
    for fd in fds:
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if not target.endswith(".jsonl"):
            continue
        for name, spec in HARNESSES.items():
            if target.startswith(str(spec["root"]) + os.sep):
                return name, target
    return None


def _slug_dirs(root: Path, cwd: str) -> list[Path]:
    """Session dirs whose slug encodes `cwd`, longest (most specific) first.

    Each harness slugifies the cwd its own way, so match on the path's own
    characters with separators neutralised rather than guessing the scheme.
    """
    want = "".join(c if c.isalnum() else "-" for c in cwd).strip("-")
    out = []
    for d in root.glob("*"):
        if not d.is_dir():
            continue
        have = "".join(c if c.isalnum() else "-" for c in d.name).strip("-")
        if have and (want == have or want.startswith(have + "-")):
            out.append(d)
    return sorted(out, key=lambda d: -len(d.name))


def resolve_session(pid: str, cwd: str) -> dict | None:
    """Identify the transcript of the session we are running inside.

    Only called from carbon_start, where this process is a child of the harness
    and so inherits its environment.
    """
    explicit = os.environ.get("CARBON_SESSION_TRANSCRIPT")
    if explicit:
        name = os.environ.get("CARBON_SESSION_HARNESS", "claude-code")
        return {"harness": name, "transcript": explicit, "how": "CARBON_SESSION_TRANSCRIPT"}

    # 1. The session id from the harness's own environment - exact and cheap.
    for name, spec in HARNESSES.items():
        for var in spec["id_env"]:
            sid = os.environ.get(var)
            if not sid:
                continue
            hits = glob(str(spec["root"] / spec["by_id"].format(id=sid)))
            if hits:
                return {
                    "harness": name,
                    "id": sid,
                    "transcript": max(hits, key=os.path.getmtime),
                    "how": f"${var}",
                }

    # 2. A transcript the harness process holds open.
    found = _newest_open_transcript(pid)
    if found:
        name, path = found
        return {"harness": name, "transcript": path, "how": f"open fd of pid {pid}"}

    # 3. Newest transcript in a session dir matching the harness cwd. Last
    #    resort: it is wrong if two sessions share a cwd, so it is labelled.
    #    Candidates from every harness compete on mtime, so the one actually
    #    being written wins rather than whichever harness is listed first.
    best = None
    for name, spec in HARNESSES.items():
        for d in _slug_dirs(Path(spec["root"]), cwd):
            for path in glob(str(d / "*.jsonl")):
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if best is None or mtime > best[0]:
                    best = (mtime, name, path, d.name)
    if best:
        _, name, path, dirname = best
        return {
            "harness": name,
            "transcript": path,
            "how": f"newest transcript in {dirname} (INFERRED from cwd)",
        }
    return None


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def collect(transcript: str, harness: str, start: datetime, end: datetime) -> Totals:
    totals = Totals()
    spec = HARNESSES.get(harness)
    if spec:
        spec["reader"](transcript, start, end, totals)
    return totals


def window(started_at: str, ended_at: str | None) -> tuple[datetime, datetime] | None:
    """The run's wall-clock window; the end is 'now' while the run is live."""
    start = _parse_ts((started_at or "").strip())
    if start is None:
        return None
    end = _parse_ts((ended_at or "").strip()) if ended_at else None
    return start, end or datetime.now(timezone.utc)


def load(started_at: str, ended_at: str | None, session: dict | None) -> list[Call] | None:
    """This run's billed requests, or None if the session is not identifiable.

    The one place a run's usage is read. Both the token section and the
    EcoLogits estimate are built from the list it returns, so they can never
    disagree about what the session did.
    """
    span = window(started_at, ended_at)
    if span is None or not session or not session.get("transcript"):
        return None
    transcript = session["transcript"]
    if not os.path.exists(transcript):
        return None
    return collect(transcript, session.get("harness", "claude-code"), *span).calls


def summary(calls: list[Call]) -> dict:
    """The session's token totals as data; `render` and `carbon compare` share it."""
    fresh = sum(c.fresh for c in calls)
    cread = sum(c.cache_read for c in calls)
    cwrite = sum(c.cache_write for c in calls)
    sent = fresh + cread + cwrite
    return {
        "calls": len(calls),
        "subagent_calls": sum(1 for c in calls if c.sidechain),
        "fresh": fresh,
        "cache_read": cread,
        "cache_write": cwrite,
        "sent": sent,
        "received": sum(c.output for c in calls),
        "thinking": sum(c.thinking for c in calls),
        "cache_hit_pct": cread / sent * 100 if sent > 0 else None,
        "average_context": sum(c.context for c in calls) // len(calls) if calls else 0,
    }


def render(
    started_at: str,
    ended_at: str | None,
    session: dict | None,
    calls: list[Call] | None = None,
) -> list[str]:
    """The Tokens section, as lines. Empty list if the time window is unusable.

    `calls` may be passed in when the caller has already loaded them (see
    `load`), so a report does not parse the transcript twice.
    """
    span = window(started_at, ended_at)
    if span is None:
        return []
    start, end = span

    out = ["  Tokens (exact, billed counts - this session only)"]

    if not session or not session.get("transcript"):
        out.append("    Session could not be identified at carbon_start, so no tokens are")
        out.append("    reported. Machine-wide counting is deliberately NOT used as a")
        out.append("    fallback: it would mix in other sessions. Set")
        out.append("    CARBON_SESSION_TRANSCRIPT to your harness's session log and re-run.")
        out.append("")
        return out

    transcript = session["transcript"]
    harness = session.get("harness", "claude-code")
    if not os.path.exists(transcript):
        out.append(f"    Transcript is gone: {transcript}")
        out.append("")
        return out

    if calls is None:
        calls = collect(transcript, harness, start, end).calls
    label = session.get("id") or Path(transcript).stem
    out.append(f"    Session       {harness}  {label}")
    if "INFERRED" in session.get("how", ""):
        out.append(f"    Matched by    {session['how']}")

    if not calls:
        out.append("    (no API calls recorded in this window)")
        out.append("")
        return out

    t = summary(calls)
    side = t["subagent_calls"]
    sent = t["sent"]

    def pct(part: int, whole: int) -> str:
        return f"{part / whole * 100:.1f}%" if whole > 0 else "-"

    out.append("")
    out.append(f"    API calls       {t['calls']:>12,d}" + (f"   ({side} in subagents)" if side else ""))
    out.append(f"    Sent            {sent:>12,d}")
    out.append(f"    Received        {t['received']:>12,d}")
    out.append(f"    Total           {sent + t['received']:>12,d}")
    out.append(f"    Cache hit %     {pct(t['cache_read'], sent):>12}")
    out.append(f"    Average context {t['average_context']:>12,d}   tokens per call")

    models: dict[str, list[int]] = {}
    for c in calls:
        m = models.setdefault(c.model, [0, 0, 0])
        m[0] += 1
        m[1] += c.context
        m[2] += c.output
    if len(models) > 1:
        out.append("")
        out.append("    By model              calls           sent       received")
        for name, (n, s, o) in sorted(models.items(), key=lambda kv: -kv[1][1]):
            out.append(f"      {name[:20]:<20} {n:6,d}  {s:13,d}  {o:13,d}")

    out.append("")
    return out


def main() -> int:
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] == "--resolve":
        pid = argv[1] if len(argv) > 1 else str(os.getppid())
        cwd = argv[2] if len(argv) > 2 else os.getcwd()
        session = resolve_session(pid, cwd)
        if not session:
            return 1
        print(json.dumps(session))
        return 0

    started = argv[0] if argv else ""
    ended = argv[1] if len(argv) > 1 and argv[1] != "-" else None
    session = json.loads(argv[2]) if len(argv) > 2 else resolve_session(str(os.getppid()), os.getcwd())
    lines = render(started, ended, session)
    if not lines:
        print(f"Unusable time window: {started!r}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
