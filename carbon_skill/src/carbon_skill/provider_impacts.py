"""Provider-side inference impacts for a carbon run, estimated with EcoLogits.

This is the *other* half of the accounting. CodeCarbon measures the electricity
this machine drew; nothing on this machine can see what the inference itself
cost, because it ran in the provider's datacenter. EcoLogits models that from
published methodology (https://ecologits.ai/latest/methodology/llm_inference/):

    energy per request  ~  f(active parameters, output tokens, batch size)
    impacts             =  energy x grid intensity  +  embodied share of the
                           server for the duration of the generation

Three properties of that model drive everything below.

1. **Only output tokens and latency enter it.** Input, cache-read and
   cache-write tokens do not appear in the formulas at all, so the enormous
   prompts a coding agent sends contribute nothing to this figure. Say so when
   reporting it: this is not "the impact of the session", it is the impact of
   generating the session's output tokens.
2. **Latency is an upper bound, not a driver.** EcoLogits takes
   `min(measured latency, modelled generation time)`, so a latency we get wrong
   on the high side changes nothing, while one we get wrong on the low side
   truncates the estimate. See `tokens.Call.latency` for how it is derived.
3. **Every figure is a range** whenever the provider does not publish its
   model's architecture, which is the usual case for a closed model: EcoLogits
   then carries a parameter-count interval. Ranges are summed bound-wise, which
   is deliberately conservative: it assumes a whole session sits at one end.

Estimation is **per request**, never on session token totals. A session mixes
models, output lengths and latencies, and the model is non-linear in all three,
so one calculation over 185k output tokens is a different number from the sum
of 183 calculations - and the wrong one. Per-request results are kept and can
be dumped with `--json`.

    python -m carbon_skill.provider_impacts --json <label|@id>   per-request results
    python -m carbon_skill.provider_impacts <label|@id>          the report section

Nothing here is a measurement of any provider's infrastructure, and nothing
here may be added to the CodeCarbon figures: different scopes, different
methods. The report text is provider-neutral for the same reason - the only
vendor-specific thing in the block is the data, which is named per model in the
`By model` table at the foot.
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    from ecologits.log import logger as _ecologits_logger
    from ecologits.model_repository import models as _registry
    from ecologits.tracers.utils import PROVIDER_CONFIG_MAP, llm_impacts
    from ecologits.utils.range_value import RangeValue

    # EcoLogits warns on stderr the first time it meets an unregistered model or
    # an unreleased architecture. Both are the norm here and both are reported
    # in the block below, so silence the stream where they would instead look
    # like the report itself had failed. (Its logger is a custom subclass, so
    # this has to happen after the import that installs it.)
    _ecologits_logger.setLevel(logging.ERROR)

    try:
        from importlib.metadata import version as _version

        VERSION = _version("ecologits")
    except Exception:
        VERSION = "?"
    AVAILABLE = True
except ImportError:  # pragma: no cover - the skill still reports tokens without it
    AVAILABLE = False
    VERSION = ""

# Zone whose electricity mix is charged to inference. Left unset, each provider
# is charged to its own datacenter location as EcoLogits records it - the honest
# default, since inference did not happen on the local grid.
ZONE = os.environ.get("CARBON_ECOLOGITS_ZONE") or None

PROVIDERS = {
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
    "azure": "openai",
    "mistral": "mistralai",
    "mistralai": "mistralai",
    "cohere": "cohere",
    "google": "google_genai",
    "google_genai": "google_genai",
    "gemini": "google_genai",
    "huggingface": "huggingface_hub",
    "huggingface_hub": "huggingface_hub",
}


# --------------------------------------------------------------------------- #
# model resolution
# --------------------------------------------------------------------------- #


def split_model(raw: str) -> tuple[str, str]:
    """(EcoLogits provider, bare model name) from whatever the harness recorded.

    Harnesses and routers each qualify a model differently, and the qualifier is
    not always the provider that actually served it, so scan every segment and
    take the last one EcoLogits recognises:

        claude-opus-5                               Claude Code
        anthropic/claude-sonnet-4-5                 pi
        openrouter/anthropic/claude-sonnet-4-5      a router in front of it
        us.anthropic.claude-opus-4-1-20250805-v1:0  Bedrock

    A dotted name is only split when one of its segments is a known provider,
    so a model whose own name contains a dot (`gpt-3.5-turbo`) survives intact.
    """
    s = (raw or "").strip()
    prefix: list[str] = []
    if "/" in s:
        *head, s = s.split("/")
        prefix += head
    if "." in s:
        head, _, tail = s.rpartition(".")
        segments = head.split(".")
        if any(seg in PROVIDERS for seg in segments):
            prefix += segments
            s = tail
    s = re.sub(r"-v\d+(:\d+)?$", "", s)
    provider = next((PROVIDERS[seg] for seg in reversed(prefix) if seg in PROVIDERS), "")
    if not provider and s.startswith("claude"):
        provider = "anthropic"
    return provider, s


def version_key(name: str) -> tuple[str, tuple[int, ...]] | None:
    """('claude-opus', (4, 1)) for 'claude-opus-4-1-20250805'.

    The trailing 8-digit date stamp is not part of the version; anything
    non-numeric ends it.
    """
    parts = name.split("-")
    if len(parts) < 3:
        return None
    ver: list[int] = []
    for p in parts[2:]:
        if p.isdigit() and len(p) != 8:
            ver.append(int(p))
        else:
            break
    if not ver:
        return None
    return "-".join(parts[:2]), tuple(ver)


def _registered(provider: str) -> list[str]:
    return [m.name for m in _registry.list_models() if m.provider.value == provider]


def resolve(provider: str, name: str) -> tuple[str, str | None, str]:
    """(provider, registry model to compute with, how we got there).

    Claude Code runs models newer than any EcoLogits release knows about
    (`claude-opus-5` today), so an exact-match-only policy would report nothing
    for every real session. Instead we fall back to the nearest registered model
    of the same family - the closest published architecture, which is the same
    kind of substitution EcoLogits itself makes when it reuses one parameter
    range across a family. It is an assumption, so it is named in the report on
    every line it affects, never folded silently into the total.
    """
    if not provider:
        # A harness that records a bare model name ("gpt-4o") still resolves,
        # as long as exactly one provider in the registry claims that name.
        owners = {m.provider.value for m in _registry.list_models() if m.name == name}
        if len(owners) != 1:
            return "", None, "no provider"
        provider = owners.pop()
        return provider, name, f"exact, provider inferred as {provider}"
    if _registry.find_model(provider=provider, model_name=name) is not None:
        return provider, name, "exact"

    key = version_key(name)
    if key is None:
        return provider, None, "unregistered"
    stem, want = key
    family = []
    for cand in _registered(provider):
        ck = version_key(cand)
        if ck and ck[0] == stem:
            family.append((ck[1], cand))
    if not family:
        return provider, None, "unregistered"
    family.sort()
    below = [c for c in family if c[0] <= want]
    _, cand = below[-1] if below else family[0]
    return provider, cand, f"proxy: nearest registered {stem.split('-')[-1]}"


# --------------------------------------------------------------------------- #
# estimation - one call at a time
# --------------------------------------------------------------------------- #


@dataclass
class Estimate:
    """One request's estimate, retained so totals can always be traced back."""

    ts: str
    model: str
    provider: str
    resolved: str | None
    how: str
    output: int
    latency: float | None
    sidechain: bool
    impacts: Any = None

    @property
    def ok(self) -> bool:
        return self.impacts is not None and not self.impacts.has_errors

    def as_dict(self) -> dict:
        d = {
            "ts": self.ts,
            "model": self.model,
            "provider": self.provider,
            "resolved_model": self.resolved,
            "resolution": self.how,
            "output_tokens": self.output,
            "latency_s": self.latency,
            "sidechain": self.sidechain,
        }
        d["impacts"] = self.impacts.model_dump() if self.ok else None
        return d


def estimate(calls) -> list[Estimate]:
    """One EcoLogits computation per billed request, in transcript order."""
    if not AVAILABLE:
        return []
    out: list[Estimate] = []
    for c in calls:
        provider, bare = split_model(c.model)
        provider, resolved, how = resolve(provider, bare)
        est = Estimate(
            ts=c.ts.isoformat(),
            model=c.model,
            provider=provider,
            resolved=resolved,
            how=how,
            output=c.output,
            latency=c.latency,
            sidechain=c.sidechain,
        )
        if resolved:
            # None -> infinity inside EcoLogits, i.e. "do not cap the modelled
            # generation time". That is the right behaviour when we could not
            # time the request: latency can only ever shrink the estimate.
            est.impacts = llm_impacts(
                provider=provider,
                model_name=resolved,
                output_token_count=c.output,
                request_latency=c.latency if c.latency is not None else float("inf"),
                electricity_mix_zone=ZONE,
            )
        out.append(est)
    return out


@dataclass
class Aggregate:
    n: int = 0
    output: int = 0
    energy: Any = 0.0
    gwp: Any = 0.0
    adpe: Any = 0.0
    pe: Any = 0.0
    wcf: Any = 0.0
    timed: int = 0


def _add(acc: Any, impact: Any) -> Any:
    return acc if impact is None else acc + impact.value


def total(ests: list[Estimate]) -> Aggregate:
    """Bound-wise sum of the per-request ranges."""
    agg = Aggregate()
    for e in ests:
        if not e.ok:
            continue
        agg.n += 1
        agg.output += e.output
        i = e.impacts
        agg.energy = _add(agg.energy, i.energy)
        agg.gwp = _add(agg.gwp, i.gwp)
        agg.adpe = _add(agg.adpe, i.adpe)
        agg.pe = _add(agg.pe, i.pe)
        agg.wcf = _add(agg.wcf, i.wcf)
        if e.latency is not None:
            agg.timed += 1
    return agg


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def _zones(ests: list[Estimate]) -> str:
    """Which grid each provider's inference is charged to.

    Not a constant: every provider EcoLogits knows has its own datacenter
    location, so a session that used two providers is charged to two grids.
    """
    if ZONE:
        return f"{ZONE}   [forced by CARBON_ECOLOGITS_ZONE, all providers]"
    parts = []
    for prov in sorted({e.provider for e in ests if e.ok}):
        cfg = PROVIDER_CONFIG_MAP.get(prov)
        parts.append(f"{cfg.datacenter_location if cfg else 'WOR'} ({prov})")
    if not parts:
        return "-"
    return ", ".join(parts) + "   [each provider's datacenter default]"


def _mean(value: Any) -> float:
    """Midpoint of a range, or the value itself.

    Not every model carries a parameter-count interval - a provider that
    publishes its architecture gets a scalar - so neither does every impact.
    """
    if AVAILABLE and isinstance(value, RangeValue):
        return value.mean
    return float(value)


PLOT_WIDTH = 60  # text columns per panel; braille gives 2 time points each
PLOT_HEIGHT = 4  # text rows per panel; braille gives 4 dot rows each
POINTS = PLOT_WIDTH * 2
YLABEL = 9
PANEL = YLABEL + 1 + PLOT_WIDTH
# Braille dot bits by [dot column][dot row, top to bottom].
BRAILLE = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
LINE_COLOR = "\033[38;2;217;119;87m"  # Claude orange, #D97757
RESET = "\033[0m"


def _color() -> bool:
    """Colour the plot lines only on a real terminal.

    The report is also captured and relayed as plain text, where escape codes
    would be noise. NO_COLOR (no-color.org) always wins; CARBON_COLOR=always
    or =never overrides the terminal check.
    """
    if os.environ.get("NO_COLOR"):
        return False
    force = os.environ.get("CARBON_COLOR", "").lower()
    if force in ("always", "never"):
        return force == "always"
    return sys.stdout.isatty()


def _span(ests: list[Estimate]) -> tuple[datetime, datetime] | None:
    """First and last modelled request time, local, or None if there are none."""
    times = [datetime.fromisoformat(e.ts).astimezone() for e in ests if e.ok]
    return (min(times), max(times)) if times else None


def _panel(label: str, ests: list[Estimate], attr: str, value: Any, scale: float, places: int) -> list[str]:
    """One impact as a small line chart over the session, PANEL columns wide.

    Requests are summed into POINTS equal wall-clock bins from the first
    request to the last, using each request's midpoint; a bin with no requests
    is 0, so idle stretches drop to the baseline. The line is drawn in braille
    dots, consecutive points joined vertically. Each panel has its own y-axis
    from 0 to its peak bin, since the units differ. The parameter-count
    uncertainty is in the total line above the chart.
    """
    if AVAILABLE and isinstance(value, RangeValue):
        lo, hi = value.min * scale, value.max * scale
        tot = f"total {lo:,.{places}f} / {(lo + hi) / 2:,.{places}f} / {hi:,.{places}f}  (lower / mean / upper)"
    else:
        tot = f"total {float(value) * scale:,.{places}f}"
    lines = [label, tot]

    t0, t1 = _span(ests)
    width = (t1 - t0).total_seconds()
    bins = [0.0] * POINTS
    for e in ests:
        impact = getattr(e.impacts, attr) if e.ok else None
        if impact is None:
            continue
        dt = (datetime.fromisoformat(e.ts).astimezone() - t0).total_seconds()
        i = min(POINTS - 1, int(POINTS * dt / width)) if width > 0 else 0
        bins[i] += _mean(impact.value) * scale

    peak = max(bins)
    dots = PLOT_HEIGHT * 4
    ys = [round((dots - 1) * v / peak) if peak > 0 else 0 for v in bins]  # 0 = bottom
    cells = [[0] * PLOT_WIDTH for _ in range(PLOT_HEIGHT)]
    for x, y in enumerate(ys):
        prev = ys[x - 1] if x else y
        for yy in range(min(prev, y), max(prev, y) + 1):
            row = dots - 1 - yy  # dot row from the top
            cells[row // 4][x // 2] |= BRAILLE[x % 2][row % 4]
    for r in range(PLOT_HEIGHT):
        row = "".join(chr(0x2800 + c) if c else " " for c in cells[r])
        if _color():
            # The row is already exactly PLOT_WIDTH wide, so the escapes cannot
            # upset the ljust(PANEL) padding below.
            row = f"{LINE_COLOR}{row}{RESET}"
        ylab = f"{peak:,.{places}f}" if r == 0 else ""
        tick = "┤" if r == 0 else "│"
        lines.append(f"{ylab:>{YLABEL - 1}} {tick}{row}")
    lines.append(f"{'0':>{YLABEL - 1}} └{'─' * PLOT_WIDTH}")
    lines.append(" " * (YLABEL + 1) + f"{t0:%H:%M}".ljust(PLOT_WIDTH - 5) + f"{t1:%H:%M}")
    return [ln.ljust(PANEL) for ln in lines]


def render(calls, ests: list[Estimate] | None = None) -> list[str]:
    """The provider-inference section, as lines. Empty if there is nothing to say.

    `ests` are the stored estimates of a finished run; computed when None.
    """
    if not calls:
        return []
    if not AVAILABLE:
        return [
            "  Provider inference (EcoLogits estimate)",
            "    Not computed: the ecologits package is not installed in this skill's venv.",
            "      Reinstall the program: uv tool install --reinstall ./carbon_skill",
            "",
        ]

    if ests is None:
        ests = estimate(calls)
    agg = total(ests)

    out = ["  Provider inference (EcoLogits estimate)"]
    if agg.n == 0:
        out.append("    No request could be matched to an EcoLogits model, so no estimate is")
        out.append("    given. Models seen: " + ", ".join(sorted({e.model for e in ests})))
        out.append("")
        return out

    out.append(f"    Method        EcoLogits {VERSION}, per request   ({agg.n:,d} of {len(ests):,d} requests modelled)")
    out.append(f"    Grid zone     {_zones(ests)}")
    out.append(f"    Priced on     {agg.output:,d} output tokens")
    out.append("")
    # Only energy is charted: the other impacts are near-fixed multiples of it
    # per request (same zone, same model), so their charts repeat its shape.
    if agg.energy is not None:
        for row in _panel("Energy (Wh)", ests, "energy", agg.energy, 1000, 3):
            out.append(("    " + row).rstrip())
        t0, t1 = _span(ests)
        per_point = (t1 - t0).total_seconds() / POINTS
        out.append(f"    Each point sums the requests in one {per_point:,.0f} s slice of the session")
        out.append("    (local time), at each request's midpoint; 0 = no requests. The y-axis")
        out.append("    runs from 0 to the highest point.")
        out.append("")

    out.append(f"    {'Other impacts, session total':<28}{'lower':>12}{'mean':>12}{'upper':>12}")
    for label, value, scale, places in (
        ("CO2e (g)", agg.gwp, 1000, 3),
        ("Water (L)", agg.wcf, 1, 3),
        ("Primary energy (MJ)", agg.pe, 1, 3),
        ("ADPe (g Sb eq)", agg.adpe, 1000, 6),
    ):
        if value is None:
            continue
        if AVAILABLE and isinstance(value, RangeValue):
            lo, hi = value.min * scale, value.max * scale
            nums = f"{lo:>12,.{places}f}{(lo + hi) / 2:>12,.{places}f}{hi:>12,.{places}f}"
        else:
            nums = f"{'-':>12}{float(value) * scale:>12,.{places}f}{'-':>12}"
        out.append(f"    {label:<28}{nums}")

    # How each model was matched - the single biggest assumption in the block.
    # Kept narrow enough not to wrap: the match note goes on its own line, and
    # with one model the per-model counts are dropped as they only repeat the
    # totals above.
    by_model: dict[tuple[str, str | None, str], list[Estimate]] = {}
    for e in ests:
        by_model.setdefault((e.model, e.resolved, e.how), []).append(e)
    groups = sorted(by_model.items(), key=lambda kv: -len(kv[1]))
    out.append("")
    if len(groups) > 1:
        out.append("    By model                  calls      output   energy Wh")
    for (model, resolved, how), group in groups:
        prov = group[0].provider
        label = split_model(model)[1] or model
        target = f"{prov}/{resolved}" if resolved else "NOT MODELLED"
        if len(groups) > 1:
            sub = total(group)
            wh = f"{_mean(sub.energy) * 1000:9,.3f}" if sub.n else "        -"
            tok = sum(e.output for e in group)
            out.append(f"      {label[:22]:<22} {len(group):6,d}  {tok:10,d}   {wh}")
            out.append(f"        computed as {target}  ({how})")
        else:
            out.append(f"    Model         {label}  ->  {target}")
            out.append(f"                  {how}")

    missing = [e for e in ests if not e.ok]
    if missing:
        lost = sum(e.output for e in missing)
        out.append("")
        out.append(f"    {len(missing):,d} request(s) and {lost:,d} output tokens are NOT in the totals above.")

    out.append("")
    out.append("    Scope         Output-token generation at the provider, modelled not")
    out.append("                  measured. A different scope from CodeCarbon; never add them.")
    out.append("")
    return out


def main() -> int:
    import json
    import sys

    from . import paths, runs, usage

    argv = sys.argv[1:]
    as_json = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if not argv:
        print("usage: python -m carbon_skill.provider_impacts [--json] <label|@id>", file=sys.stderr)
        return 2
    try:
        run = runs.find(argv[0])
    except (paths.Failure, paths.UsageError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not run.get("started_at"):
        print(f"Run {runs.name(run)} never started.", file=sys.stderr)
        return 1
    calls, ests = usage.for_report(run)
    if calls is None:
        print("Session could not be identified; no usage to estimate from.", file=sys.stderr)
        return 1

    if as_json:
        if ests is None:
            ests = estimate(calls)
        agg = total(ests)
        print(
            json.dumps(
                {
                    "method": {"tool": "ecologits", "version": VERSION, "zone": ZONE, "granularity": "per-request"},
                    "totals": {
                        "requests_modelled": agg.n,
                        "requests_total": len(ests),
                        "output_tokens": agg.output,
                        "energy_kWh": _dump(agg.energy),
                        "gwp_kgCO2eq": _dump(agg.gwp),
                        "wcf_L": _dump(agg.wcf),
                        "pe_MJ": _dump(agg.pe),
                        "adpe_kgSbeq": _dump(agg.adpe),
                    },
                    "requests": [e.as_dict() for e in ests],
                },
                indent=1,
                default=str,
            )
        )
        return 0

    print("\n".join(render(calls, ests)))
    return 0


def summary(calls, ests: list[Estimate] | None = None) -> dict | None:
    """Session totals as (low, high) pairs in Wh and g, or None if nothing was modelled."""
    if not calls or not AVAILABLE:
        return None
    agg = total(ests if ests is not None else estimate(calls))
    if agg.n == 0:
        return None

    def bounds(value: Any, scale: float) -> tuple[float, float] | None:
        if value is None:
            return None
        if isinstance(value, RangeValue):
            return value.min * scale, value.max * scale
        return float(value) * scale, float(value) * scale

    return {
        "requests_modelled": agg.n,
        "output_tokens": agg.output,
        "energy_wh": bounds(agg.energy, 1000),
        "co2e_g": bounds(agg.gwp, 1000),
    }


def _dump(value: Any) -> Any:
    if AVAILABLE and isinstance(value, RangeValue):
        return {"min": value.min, "max": value.max}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
