"""carbon compare: two runs side by side, or a task with an idle baseline subtracted."""

from __future__ import annotations

from . import paths, provider_impacts, report, runs, tokens, usage


def _data(ref: str) -> dict:
    run = runs.find(ref)
    f = report.figures(run["id"])
    if f is None:
        raise paths.Failure(f"Run {runs.name(run)} has no measurement yet.")
    d = {
        "Duration (s)": f["duration"],
        "Energy (Wh)": f["energy"] * 1000,
        "  CPU (Wh)": f["cpu_energy"] * 1000,
        "  GPU (Wh)": f["gpu_energy"] * 1000,
        "  RAM (Wh)": f["ram_energy"] * 1000,
        "CO2e (g)": f["emissions"] * 1000,
        "_cpu_method": run.get("cpu_method") or "unknown",
        "_live": runs.is_live(run),
    }
    calls, ests = usage.for_report(run)
    if calls:
        t = tokens.summary(calls)
        d.update({
            "API calls": t["calls"],
            "Tokens sent": t["sent"],
            "Tokens received": t["received"],
            "Cache hit %": t["cache_hit_pct"],
            "Average context": t["average_context"],
        })
        try:
            p = provider_impacts.summary(calls, ests)
        except Exception:
            p = None
        if p:
            for key, name in (("energy_wh", "EcoLogits energy (Wh)"), ("co2e_g", "EcoLogits CO2e (g)")):
                if p.get(key):
                    d[f"{name} low"], d[f"{name} high"] = p[key]
    return d


MACHINE = ["Duration (s)", "Energy (Wh)", "  CPU (Wh)", "  GPU (Wh)", "  RAM (Wh)", "CO2e (g)"]
USAGE = ["API calls", "Tokens sent", "Tokens received", "Cache hit %", "Average context"]
PROVIDER = [
    "EcoLogits energy (Wh) low", "EcoLogits energy (Wh) high",
    "EcoLogits CO2e (g) low", "EcoLogits CO2e (g) high",
]


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, int):
        return f"{v:,d}"
    return f"{v:,.3f}" if abs(v) < 1000 else f"{v:,.0f}"


def _row(name: str, a, b) -> str:
    if a is None or b is None:
        delta, pct = "-", "-"
    else:
        delta = _fmt(b - a)
        if isinstance(a, int) and isinstance(b, int):
            delta = f"{b - a:+,d}"
        elif not delta.startswith("-"):
            delta = "+" + delta
        pct = f"{(b - a) / a * 100:+.1f}%" if a else "-"
    return f"  {name:<28}{_fmt(a):>14}{_fmt(b):>14}{delta:>14}{pct:>9}"


FOOTER = [
    "  [Relay the block above verbatim, in a code block, and stop. Do not",
    "   summarise, reformat, recompute or add assumptions of your own.",
    "   Machine rows are WHOLE-MACHINE measurements: a difference is not caused",
    "   by any one program, and one pair of runs can be noise - repeat before",
    "   concluding. Never add the EcoLogits rows to the machine rows.]",
]


def command(a: str, b: str, baseline: bool) -> int:
    runs.sweep()
    da, db = _data(a), _data(b)
    warn = []
    if da["_cpu_method"] != db["_cpu_method"]:
        warn.append(
            f"  WARNING: CPU power was {da['_cpu_method']} in '{a}' and {db['_cpu_method']} in '{b}';"
            " this compares a measurement with an estimate."
        )
    for label, d in ((a, da), (b, db)):
        if d["_live"]:
            warn.append(f"  NOTE: '{label}' is still running; its figures are not final.")

    if baseline:
        return _baseline(a, b, da, db, warn)

    print(f"carbon compare - '{b}' against '{a}'")
    print()
    print(f"  {'':<28}{a[:14]:>14}{b[:14]:>14}{'change':>14}{'%':>9}")
    for group in (MACHINE, USAGE, PROVIDER):
        for name in group:
            print(_row(name, da.get(name), db.get(name)))
        print()
    for line in warn:
        print(line)
    if warn:
        print()
    print("\n".join(FOOTER))
    return 0


def _baseline(idle: str, task: str, di: dict, dt: dict, warn: list[str]) -> int:
    idur, tdur = di["Duration (s)"], dt["Duration (s)"]
    if idur <= 0:
        raise paths.Failure(f"Idle run '{idle}' has zero duration; cannot scale it.")
    scale = tdur / idur
    print(f"carbon compare - '{task}' above idle baseline '{idle}'")
    print(f"  idle scaled to {tdur:,.0f} s (x{scale:.3f})")
    print()
    print(f"  {'':<28}{'task':>14}{'idle scaled':>14}{'above idle':>14}")
    for name in MACHINE[1:]:
        t, i = dt[name], di[name] * scale
        print(f"  {name:<28}{_fmt(t):>14}{_fmt(i):>14}{_fmt(t - i):>14}")
    print()
    for line in warn:
        print(line)
    if warn:
        print()
    print("\n".join(FOOTER))
    return 0
