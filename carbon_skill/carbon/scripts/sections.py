"""The usage half of a carbon report, shared by the final and live reports.

Two sections, built from one read of the session transcript:

    Tokens              what the session actually sent and received - measured,
                        in the sense that the provider billed it (tokens.py)
    Provider inference  what that generation plausibly cost in the provider's
                        datacenter - estimated, never measured
                        (provider_impacts.py)

They are deliberately separate modules and separate blocks in the report. The
CodeCarbon figures above them measure this machine; these do not. Nothing here
is ever added to them.
"""

from __future__ import annotations

import json
import os


def read(rundir: str, name: str) -> str | None:
    try:
        with open(os.path.join(rundir, name)) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def usage_sections(rundir: str | None) -> list[str]:
    """Both sections for this run, or nothing if they cannot be determined.

    Failure is always silent-and-empty rather than fatal: a report that lost its
    token section is still a valid energy report, and an EcoLogits failure must
    never take the token counts down with it.
    """
    if not rundir:
        return []
    try:
        import tokens
    except ImportError:
        return []

    started = read(rundir, "started_at")
    if not started:
        return []
    ended = read(rundir, "ended_at")
    raw = read(rundir, "session.json")
    try:
        session = json.loads(raw) if raw else None
    except ValueError:
        session = None

    try:
        calls = tokens.load(started, ended, session)
    except Exception:
        calls = None

    try:
        out = tokens.render(started, ended, session, calls)
    except Exception:
        return []
    if not out:
        return []

    if calls:
        try:
            import provider_impacts

            out += provider_impacts.render(calls)
        except Exception:
            pass
    return out


def footer(usage: list[str]) -> list[str]:
    """The closing instruction, naming only the scopes actually in the report."""
    out = [
        "  [Relay the block above verbatim, in a code block, and stop. Do not",
        "   summarise, reformat, recompute or add assumptions of your own.",
        "   The CodeCarbon figures are a WHOLE-MACHINE measurement: they attribute",
        "   energy to no program, so never speculate about what caused the usage.",
    ]
    if any("EcoLogits estimate" in line for line in usage):
        out += [
            "   The EcoLogits figures are an ESTIMATE of provider-side inference, over",
            "   output tokens only. Quote them with their range, name the model they",
            "   were computed for, and never add them to the CodeCarbon energy.",
        ]
        if any("(proxy:" in line for line in usage):
            out.append("   At least one model is a STAND-IN - say so; see the By model table.")
        out[-1] += "]"
    else:
        out[-1] += "]"
    return out
