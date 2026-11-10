"""Saving a finished run's tokens and EcoLogits estimates, and reading them back.

The counting (`tokens.load`) and the estimate (`provider_impacts.estimate`) are
unchanged; this module only decides where their results come from. Once a run
has stopped they are saved, so its report no longer needs the transcript,
which the harness may delete.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import db

# Impact name -> (column stem). Units: kWh, kgCO2eq, kgSbeq, MJ, L (EcoLogits').
IMPACTS = {"energy": "energy_kwh", "gwp": "gwp_kg", "adpe": "adpe_kg", "pe": "pe_mj", "wcf": "wcf_l"}


def save(run_id: int) -> bool:
    """Store the run's calls and estimates (replacing any already stored).

    Returns True if saved. If the session or its transcript is missing, or the
    computation fails, sets `usage_note` instead and returns False.
    """
    from . import provider_impacts, tokens

    run = db.get_run(run_id)
    if run is None or not run.get("started_at"):
        return False
    session = run.get("session")
    if not session or not session.get("transcript"):
        db.update_run(run_id, usage_note="session not identified at carbon start")
        return False
    try:
        calls = tokens.load(run["started_at"], run.get("ended_at"), session)
    except Exception as exc:
        db.update_run(run_id, usage_note=f"transcript unreadable: {exc!r}")
        return False
    if calls is None:
        db.update_run(run_id, usage_note=f"transcript gone: {session['transcript']}")
        return False
    try:
        ests = provider_impacts.estimate(calls) if provider_impacts.AVAILABLE else None
    except Exception as exc:
        print(f"carbon: EcoLogits failed for run @{run_id}: {exc!r}", file=sys.stderr)
        ests = None

    rows = [
        {"seq": i, "ts": c.ts.isoformat(), "model": c.model, "fresh": c.fresh, "cache_read": c.cache_read,
         "cache_write": c.cache_write, "output": c.output, "thinking": c.thinking,
         "sidechain": int(bool(c.sidechain)), "latency_s": c.latency}
        for i, c in enumerate(calls, 1)
    ]
    est_rows = [_estimate_row(e) for e in ests] if ests is not None else [None] * len(rows)
    db.save_usage(run_id, rows, est_rows, {
        "usage_saved_at": db.now_iso(),
        "usage_note": None,
        # NULL version: no estimates were stored, so a report recomputes them.
        "ecologits_version": provider_impacts.VERSION if ests is not None else None,
        "ecologits_zone": provider_impacts.ZONE,
    })
    return True


def _bounds(impact: Any) -> tuple[float | None, float | None]:
    if impact is None:
        return None, None
    v = impact.value
    if hasattr(v, "min") and hasattr(v, "max"):
        return float(v.min), float(v.max)
    return float(v), float(v)


def _estimate_row(e) -> dict:
    row = {"provider": e.provider or "", "model_used": e.resolved, "how": e.how}
    for attr, stem in IMPACTS.items():
        impact = getattr(e.impacts, attr, None) if e.ok else None
        row[f"{stem}_low"], row[f"{stem}_high"] = _bounds(impact)
    return row


# --------------------------------------------------------------------------- #
# reading back
# --------------------------------------------------------------------------- #


@dataclass
class _Impact:
    value: Any


class StoredImpacts:
    """Stands in for EcoLogits' ImpactsOutput, rebuilt from stored bounds, so the
    existing render code prints exactly what it printed from the live object."""

    has_errors = False

    def __init__(self, row: dict) -> None:
        from .provider_impacts import AVAILABLE

        for attr, stem in IMPACTS.items():
            lo, hi = row[f"est_{stem}_low"], row[f"est_{stem}_high"]
            if lo is None:
                setattr(self, attr, None)
            elif lo == hi or not AVAILABLE:
                setattr(self, attr, _Impact(lo))
            else:
                from ecologits.utils.range_value import RangeValue

                setattr(self, attr, _Impact(RangeValue(min=lo, max=hi)))

    def model_dump(self) -> dict:
        out = {}
        for attr in IMPACTS:
            imp = getattr(self, attr)
            v = None if imp is None else imp.value
            out[attr] = {"value": v.model_dump() if hasattr(v, "model_dump") else v}
        return out


def load(run: dict) -> tuple[list | None, list | None]:
    """(calls, estimates) for a stopped run with saved usage, else (None, None).

    `estimates` is None when they were not stored; callers then compute them.
    """
    from . import provider_impacts, tokens

    if run.get("state") in db.LIVE or not run.get("usage_saved_at"):
        return None, None
    rows = db.load_usage(run["id"])
    calls = [
        tokens.Call(ts=datetime.fromisoformat(r["ts"]), model=r["model"], fresh=r["fresh"],
                    cache_read=r["cache_read"], cache_write=r["cache_write"], output=r["output"],
                    thinking=r["thinking"], sidechain=bool(r["sidechain"]), latency=r["latency_s"])
        for r in rows
    ]
    if not run.get("ecologits_version") or any(r["est_provider"] is None for r in rows):
        return calls, None
    ests = []
    for r, c in zip(rows, calls):
        has = r["est_energy_kwh_low"] is not None or any(r[f"est_{s}_low"] is not None for s in IMPACTS.values())
        ests.append(provider_impacts.Estimate(
            ts=r["ts"], model=r["model"], provider=r["est_provider"], resolved=r["est_model_used"],
            how=r["est_how"], output=c.output, latency=c.latency, sidechain=c.sidechain,
            impacts=StoredImpacts(r) if has else None,
        ))
    return calls, ests


def for_report(run: dict) -> tuple[list | None, list | None]:
    """The calls (and stored estimates, if any) a report or compare should use:
    saved ones for a finished run, else read from the transcript as it is now."""
    from . import tokens

    calls, ests = load(run)
    if calls is not None:
        return calls, ests
    if not run.get("started_at"):
        return None, None
    try:
        return tokens.load(run["started_at"], run.get("ended_at"), run.get("session")), None
    except Exception:
        return None, None
